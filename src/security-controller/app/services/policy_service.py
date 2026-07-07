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
from app.utils import tenancy
from app.validators.cedar import policy_artifact
from app.utils.cache_manager import get_cache_manager
from app.utils.pagination import decode_cursor, next_token_from_response
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
        
        # Cache manager
        self.cache = get_cache_manager()
        self.cache_ttl = settings.policy_cache_ttl_seconds
        
        # Metrics namespace
        self.metrics_namespace = "AgentManagementAPI"

    # Resolved per-call so TENANCY_V2_ENABLED is honored live (workstream T7).
    @property
    def policies_metadata_table(self):
        return self.dynamodb.Table(tenancy.table_name('policies_metadata'))

    async def query_policies(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None
    ) -> Dict:
        """
        Query policies from DynamoDB metadata table with filters.

        Args:
            agent_id: Filter by agent ID (optional)
            status: Filter by status (active/inactive/deprecated) (optional)
            limit: Max results (default: 50, max: 200)
            cursor: Opaque pagination token from a prior call (optional)

        Returns:
            Dict with policies, total, next_token (canonical pagination, LLD 21 §11.1)
        """
        start_time = time.time()
        cache_hit = False

        try:
            # Build cache key (cursor included so pages don't collide). Tenant-
            # scoped (WS-N): the list-all path (agent_id=None) reads via
            # query_or_scan(current_tenant()), but this cache is the PROCESS-GLOBAL
            # singleton with no per-request reset — a tenant-less key would serve
            # tenant A's policies to tenant B (cross-tenant leak). Prefix with the
            # bound tenant, mirroring policy_engine's `policy_bundle:{current_tenant()}:`.
            cache_key = (
                f"policies:{tenancy.current_tenant()}:agent={agent_id}:"
                f"status={status}:limit={limit}:cursor={cursor}"
            )
            # Decode the opaque cursor into a DDB ExclusiveStartKey (ValueError → 400 upstream).
            start_key = decode_cursor(cursor) if cursor else None
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
            
            metadata_table = self.policies_metadata_table
            if agent_id:
                # Use agent-index GSI (composite tenant_agent_id PK when v2).
                logger.info(f"Querying policies for agent: {agent_id}")
                agent_kce, agent_val = tenancy.agent_index_kce_value(agent_id)
                response = metadata_table.query(
                    IndexName='agent-index',
                    KeyConditionExpression=agent_kce,
                    ExpressionAttributeValues={':agent_id': agent_val},
                    Limit=limit,
                    **({"ExclusiveStartKey": start_key} if start_key else {})
                )
                policies = response.get('Items', [])

            elif status:
                # Use status-index GSI (tenant_id + status PK/SK when v2).
                logger.info(f"Querying policies with status: {status}")
                status_kce, status_names, status_values = tenancy.status_index_query(status)
                response = metadata_table.query(
                    IndexName='status-index',
                    KeyConditionExpression=status_kce,
                    ExpressionAttributeNames=status_names,
                    ExpressionAttributeValues=status_values,
                    Limit=limit,
                    **({"ExclusiveStartKey": start_key} if start_key else {})
                )
                policies = response.get('Items', [])

            else:
                # Scan all policies (no filters) → tenant-scoped Query when v2.
                logger.info("Scanning all policies")
                response = tenancy.query_or_scan(
                    metadata_table,
                    Limit=limit,
                    **({"ExclusiveStartKey": start_key} if start_key else {})
                )
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
                "next_token": next_token_from_response(response),
            }
            
            # Cache result
            self.cache.set(cache_key, result, ttl=self.cache_ttl)
            
            # Publish metrics
            self._publish_metrics("GetPolicies", time.time() - start_time, cache_hit)
            
            return result
            
        except Exception as e:
            logger.exception("Error querying policies")
            # Return empty array on error (fail-safe for Dashboard)
            return {"policies": [], "total": 0, "next_token": None, "error": str(e)}
    
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
            response = self.policies_metadata_table.get_item(Key=tenancy.item_key('policy_id', policy_id))
            
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
            
            # Download full content from S3 (B3 dual-read across legacy/explicit).
            logger.info(f"Loading policy content from S3: {s3_key}")
            from app.utils.s3_policy_store import get_policy_object
            policy_obj = get_policy_object(self.s3_client, s3_bucket, s3_key)
            policy_content = policy_obj['Body'].read().decode('utf-8')
            
            # Parse the structured source (always the editor's source of truth).
            policy_data = yaml.safe_load(policy_content)

            # Surface policy_format + the READ-ONLY generated Cedar (CT12/CT13).
            # The structured view stays the only editor (single source of truth,
            # Kiro #6); cedar_content is preview-only. Loaded from the .cedar
            # co-artifact (CT06c); best-effort so a missing co-artifact never
            # fails the detail view.
            policy_format = metadata.get(policy_artifact.POLICY_FORMAT_FIELD, policy_artifact.FORMAT_YAML)
            policy_data['policy_format'] = policy_format
            if policy_format == policy_artifact.FORMAT_CEDAR:
                try:
                    policy_data['cedar_content'] = policy_artifact.load_compiled_policies(
                        self.s3_client, s3_bucket, s3_key)
                except Exception:
                    logger.warning(f"Cedar co-artifact missing for {policy_id}; preview omitted")

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
            # PolicyCreateRequest omits the server-generated envelope fields, but validate_policy
            # checks the full AgentPolicyDocument schema, which REQUIRES policy_id/status/created_at/
            # created_by. Generate them up front so a well-formed create request validates, instead of
            # being rejected on these required-but-server-owned fields (this previously made
            # POST /v1/policies fail for every create).
            policy_id = f"agent-config-{policy_data['agent_id']}"
            now = datetime.utcnow().isoformat() + 'Z'
            policy_data = dict(policy_data)
            policy_data.setdefault('policy_id', policy_id)
            policy_data.setdefault('status', 'active')
            policy_data.setdefault('created_at', now)
            policy_data.setdefault('updated_at', now)
            policy_data.setdefault('created_by', operator_email)

            # 1. Validate (now a complete AgentPolicyDocument)
            validator = PolicyValidator()
            is_valid, errors = validator.validate_policy(policy_data)
            if not is_valid:
                logger.warning(f"Policy validation failed: {errors}")
                await metrics_publisher.publish_policy_validation_metric('SCHEMA_ERROR', len(errors))
                raise ValidationException(errors)

            # 2. Check if policy already exists
            existing = await self.get_policy(policy_id)
            if existing:
                await metrics_publisher.publish_policy_crud_metric('CREATE_POLICY', False, agent_id)
                raise ConflictException(f"Policy {policy_id} already exists", existing.get('version'))

            # 3. Generate content hash
            yaml_content = yaml.dump(policy_data, sort_keys=False)
            content_hash = f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}"

            # 4. Upload to S3 (configured artifacts bucket, NOT the hardcoded default which
            # doesn't exist in deployed accounts — the bucket name is CDK-suffixed).
            s3_store = S3PolicyStore(bucket_name=settings.s3_bucket)
            version = policy_data['version']
            # B3: explicit per-tenant key when enabled, else legacy implicit layout.
            s3_key = tenancy.policy_s3_object_key(policy_data['agent_id'], version)
            s3_version_id = await s3_store.upload(
                key=s3_key,
                content=yaml_content,
                metadata={'policy_id': policy_id, 'version': version}
            )

            # 4b. Born-Cedar on save (CT12) — only when the Cedar feature is on.
            # Generates + schema-validates the `.cedar` co-artifact and writes it
            # beside the structured source (CT06c); a schema-invalid result is a
            # VALIDATION_ERROR. When cedar is disabled (default) the policy stays
            # structured-only and the CT08 backfill migrates it later.
            policy_format, generator_version = self._maybe_write_cedar(
                policy_id, policy_data, s3_key)

            # 5. Store metadata in DynamoDB (now already computed above)
            metadata_item = {
                'policy_id': policy_id,
                'agent_id': policy_data['agent_id'],
                'name': policy_data['name'],
                'version': version,
                'status': 'active',
                's3_bucket': settings.s3_bucket,
                's3_key': s3_key,
                's3_version_id': s3_version_id,
                'allowed_tools_count': len(policy_data['allowed_tools']),
                'policies_count': len(policy_data['policies']),
                'severity_breakdown': self._calculate_severity_breakdown(policy_data['policies']),
                'content_hash': content_hash,
                'schema_version': policy_data.get('schema_version', 'v1'),
                'policy_format': policy_format,
                'created_at': now,
                'updated_at': now,
                'created_by': operator_email,
                'last_updated_by': operator_email
            }
            if generator_version:
                metadata_item['generator_version'] = generator_version

            # Stamp tenant_id (base PK) + composite tenant_agent_id (agent-index
            # GSI) when v2 is on; no-op otherwise (workstream T04).
            tenancy.stamp_agent_gsi(tenancy.stamp_base_item(metadata_item))
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

        # 3. Compute the new version FIRST. The editor OMITS version on edit so we
        #    auto-increment (agent-policy-management §6.3 / K10). This MUST happen
        #    before validation: the policy schema requires `version`, so validating
        #    a version-less body would 400 ("Schema error at version: Field
        #    required") even though we're about to assign one.
        new_version = policy_data.get('version') or self._increment_version(existing['version'])

        # 4. Merge with existing metadata for validation (incl. the resolved
        #    version + system-owned fields the user doesn't send).
        policy_data_with_metadata = {
            **policy_data,
            'policy_id': policy_id,
            'version': new_version,
            'status': existing.get('status', 'active'),
            'created_at': existing.get('created_at'),
            'created_by': existing.get('created_by')
        }

        # 5. Validate
        validator = PolicyValidator()
        is_valid, errors = validator.validate_policy(policy_data_with_metadata)
        if not is_valid:
            raise ValidationException(errors)

        # 5. Generate content hash
        yaml_content = yaml.dump(policy_data, sort_keys=False)
        content_hash = f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}"

        # 6. Upload to S3 (use existing bucket from metadata)
        bucket_name = existing.get('s3_bucket', 'sentra-mvp-artifacts')
        s3_store = S3PolicyStore(bucket_name=bucket_name)
        # B3: explicit per-tenant key when enabled, else legacy implicit layout.
        s3_key = tenancy.policy_s3_object_key(policy_data['agent_id'], new_version)
        s3_version_id = await s3_store.upload(
            key=s3_key,
            content=yaml_content,
            metadata={'policy_id': policy_id, 'version': new_version}
        )

        # 6b. Born-Cedar on update (CT12): regenerate + write the `.cedar` for the
        # NEW version when cedar is on; else reset to structured (the new version
        # has no compiled .cedar until the CT08 backfill regenerates it — CT06c).
        policy_format, generator_version = self._maybe_write_cedar(
            policy_id, policy_data, s3_key)

        # 7. Update metadata
        now = datetime.utcnow().isoformat() + 'Z'
        self.policies_metadata_table.update_item(
            Key=tenancy.item_key('policy_id', policy_id),
            UpdateExpression="""
                SET version = :version,
                    s3_key = :s3_key,
                    s3_version_id = :s3_version_id,
                    content_hash = :content_hash,
                    policy_format = :policy_format,
                    generator_version = :generator_version,
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
                ':policy_format': policy_format,
                # None when structured-only; stored so the cache key + staleness
                # detection see a consistent value across create/update.
                ':generator_version': generator_version,
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
            Key=tenancy.item_key('policy_id', policy_id),
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

    async def set_policy_status(
        self,
        policy_id: str,
        status: str,
        operator_email: str
    ) -> Dict:
        """
        Enable or disable a policy (lifecycle status flip).

        agent-policy-management §4.3 / T20. `active` = enable (the previously
        missing re-enable capability); `disabled` = disable (alias of soft-delete).
        The engine reads this status when resolving an agent's bound policy:
        flipping to `disabled` fail-secure DENYs every bound agent (POLICY_DISABLED);
        flipping to `active` restores them.

        §2.8 (DECIDED): there is **no** `created_by=='system'` 403 here —
        Enable/Disable are allowed on seeded (system) policies. Only DELETE stays
        protected (see delete_policy). Do not mirror delete's guard.

        Args:
            policy_id: Policy identifier
            status: "active" | "disabled"
            operator_email: Operator performing the change

        Returns:
            Dict with success, policy_id, status, updated_at

        Raises:
            ValidationException: invalid status
            NotFoundException: policy not found
        """
        from datetime import datetime

        if status not in ('active', 'disabled'):
            raise ValidationException(
                ["status must be 'active' or 'disabled'"]
            )

        existing = await self.get_policy(policy_id)
        if not existing:
            raise NotFoundException(f"Policy {policy_id} not found")

        now = datetime.utcnow().isoformat() + 'Z'
        self.policies_metadata_table.update_item(
            Key=tenancy.item_key('policy_id', policy_id),
            UpdateExpression="SET #status = :status, updated_at = :now, last_updated_by = :operator",
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': status,
                ':now': now,
                ':operator': operator_email
            }
        )

        operation = 'ENABLE_POLICY' if status == 'active' else 'DISABLE_POLICY'
        self._log_audit(operation, policy_id, operator_email, {'status': status})

        # Clear cache so the next read reflects the new status. (Per-process
        # cache; multi-task staleness is TTL-bounded — agent-policy-management
        # K7 — there is no cross-task invalidation claim.)
        self.cache.clear()

        logger.info(f"Set policy {policy_id} status to {status}")

        return {
            'success': True,
            'policy_id': policy_id,
            'status': status,
            'updated_at': now
        }

    def _maybe_write_cedar(self, policy_id: str, policy_data: Dict, s3_key: str):
        """Born-Cedar on save (CT12). When `cedar_enabled`, generate the `.cedar`
        co-artifact, schema-validate it, and write it beside the structured source
        (CT06c). Returns `(policy_format, generator_version)`.

        When cedar is disabled (default) this is a no-op returning
        `(FORMAT_YAML, None)` — the save path stays byte-identical to pre-Cedar.
        A schema-invalid generated policy raises ValidationException (the on-save
        Cedar schema check that replaces the syntax-only check — CT11/CT12).
        """
        if not settings.cedar_enabled:
            return policy_artifact.FORMAT_YAML, None

        # Lazy import so cedarpy only loads when the feature is on.
        from app.validators.cedar.evaluator import validate_policy_set
        from app.validators.cedar.generator import GENERATOR_VERSION, generate_cedar

        cedar_text = generate_cedar(policy_id, policy_data)
        errors = validate_policy_set(cedar_text)
        if errors:
            logger.error("Generated Cedar for %s failed schema validation: %s", policy_id, errors)
            raise ValidationException([f"Cedar schema validation: {e}" for e in errors])

        policy_artifact.put_compiled_policies(
            self.s3_client, settings.s3_bucket, s3_key, cedar_text,
            metadata={'policy_id': policy_id, 'generator_version': GENERATOR_VERSION})
        logger.info("Born-Cedar: wrote .cedar co-artifact for %s (generator %s)", policy_id, GENERATOR_VERSION)
        return policy_artifact.FORMAT_CEDAR, GENERATOR_VERSION

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
