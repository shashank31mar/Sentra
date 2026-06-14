"""
Policy Engine - Step 2 of Validation Pipeline

Validates agent authorization and tool permissions.
Checks if agent is allowed to use the requested tool and invoke other agents.

Requirements: LLD 03 Section 3.3, 8.1
Updated: Task 1.7 - Hybrid DynamoDB + S3 storage
"""
import asyncio
import logging
from typing import Dict, Optional

import boto3
import yaml
from botocore.exceptions import ClientError

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings
from app.utils import tenancy
from app.utils.cache_manager import get_cache_manager
from app.utils.cloud import resolve_cloud_region
from app.validators._signal_stamp import stamps

logger = logging.getLogger(__name__)


class PolicyNotFoundError(Exception):
    """Raised when agent policy doesn't exist (no binding, no fallback policy)."""
    pass


class PolicyDisabledError(PolicyNotFoundError):
    """Raised when the agent's BOUND policy exists but is lifecycle-disabled.

    Subclasses PolicyNotFoundError so existing `except PolicyNotFoundError`
    handlers (context_validator, cross_agent_validator) still fail-secure DENY,
    while the policy engine can catch this first to emit the precise
    POLICY_DISABLED reason (agent-policy-management §4.1 / T14).
    """
    pass


class PolicyEngine:
    """
    Validates agent policies and tool permissions.
    
    Uses hybrid storage approach (Task 1.7):
    - DynamoDB: Policy metadata (sentra-policies-metadata)
    - S3: Full policy YAML content
    
    Checks:
    - Is tool authorized for this agent?
    - If invoking another agent, is that allowed?
    """
    
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
        self.s3_client = boto3.client('s3', region_name=settings.aws_region)
        # WS24 M3.5: shared process-wide TTL+LRU cache (WS5 framework) for the
        # resolved policy bundle — collapses the up-to-3× per-request DDB+S3
        # loads (Cedar STEP 2 / context STEP 4 / abuse STEP 5) to one.
        self.cache = get_cache_manager()

    # Tables are resolved per-call (not latched at __init__) so the
    # TENANCY_V2_ENABLED flag is honored live on the hot path (workstream T7).
    # boto3 Table() is a cheap name-binding (no I/O), so this adds no latency.
    @property
    def metadata_table(self):
        return self.dynamodb.Table(tenancy.table_name('policies_metadata'))

    @property
    def agent_registry(self):
        # agent-policy-management N3/K5: the engine resolves the agent's *binding*
        # (attached_policy_id) and the agent's *cloud identity* from the registry.
        return self.dynamodb.Table(tenancy.table_name('agent_registry'))

    def _get_agent_record(self, agent_id: str) -> Dict:
        """Single registry get_item. Returns {} if the agent isn't registered
        (the GSI fallback can still find a policy by agent_id)."""
        try:
            return self.agent_registry.get_item(
                Key=tenancy.item_key('agent_id', agent_id)
            ).get('Item') or {}
        except ClientError:
            logger.exception(f"Registry read failed for agent {agent_id}")
            return {}

    def get_agent_cloud_identity(self, agent_id: str) -> tuple[Optional[str], Optional[str]]:
        """(platform, cloud_region) resolved from the AGENT record alone.

        Used by the early trust-check DENY path (validation_service) which returns
        BEFORE the policy loads (agent-policy-management K9/R4). No policy is
        consulted here; cloud_region falls back to a hosting-cloud default.
        """
        agent = self._get_agent_record(agent_id)
        return agent.get('platform'), resolve_cloud_region(agent)

    def _resolve_policy_metadata(self, agent_id: str, agent: Dict) -> Dict:
        """Resolve the agent's governing policy METADATA row via its binding.

        Resolution order (agent-policy-management §2.2/§2.6):
          1. If the agent has `attached_policy_id`, load THAT policy by its stored
             id (never reconstructed — §2.7/K2). Require it to be lifecycle-active
             (else POLICY_DISABLED).
          2. If the agent has no binding, fall back to the legacy `agent-index`
             GSI lookup (`status=active`) during migration (§2.6). Once the
             backfill is verified, no binding == POLICY_NOT_FOUND.

        Returns the DynamoDB metadata item (carries s3_bucket/s3_key, content_hash,
        schema_version, generator_version, policy_format — everything the Cedar
        loader needs for the co-artifact key + cache key, CT06).

        Raises PolicyDisabledError / PolicyNotFoundError as before.
        """
        bound_policy_id = agent.get('attached_policy_id')

        if bound_policy_id:
            # Binding path — load the bound policy by its STORED id (K2).
            metadata = self.metadata_table.get_item(
                Key=tenancy.item_key('policy_id', bound_policy_id)
            ).get('Item')
            if not metadata:
                # Binding points at a vanished policy — fail-secure.
                logger.error(
                    f"Agent {agent_id} bound to missing policy {bound_policy_id}"
                )
                raise PolicyNotFoundError(
                    f"Bound policy {bound_policy_id} for agent {agent_id} not found"
                )
            if metadata.get('status') != 'active':
                logger.warning(
                    f"Agent {agent_id} bound policy {bound_policy_id} is "
                    f"{metadata.get('status')!r} (disabled)"
                )
                raise PolicyDisabledError(
                    f"Bound policy {bound_policy_id} for agent {agent_id} is disabled"
                )
            return metadata

        # Migration fallback (§2.6): resolve the active policy via the GSI,
        # exactly as the engine did before the binding existed. The
        # agent-index PK is the composite `tenant_agent_id` when v2 is on.
        agent_kce, agent_val = tenancy.agent_index_kce_value(agent_id)
        response = self.metadata_table.query(
            IndexName='agent-index',
            KeyConditionExpression=agent_kce,
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':agent_id': agent_val,
                ':status': 'active'
            },
            Limit=1,
            ScanIndexForward=False  # latest version first
        )
        if not response.get('Items'):
            logger.error(f"No active policy found for agent: {agent_id}")
            raise PolicyNotFoundError(f"Agent {agent_id} has no active policy")
        metadata = response['Items'][0]
        logger.debug(
            f"Agent {agent_id} unbound; resolved via GSI fallback to "
            f"{metadata.get('policy_id')}"
        )
        return metadata

    def _load_structured_policy(self, agent_id: str, agent: Dict, metadata: Dict) -> Dict:
        """Download the structured policy SOURCE from S3 and stamp cloud-from-agent.

        This is the source of truth (CT06c) — full structured dict with
        allowed_tools / allowed_agents / allowed_callers / cross_cloud_dependencies
        / max_refund_amount / max_calls_per_minute. NEVER parsed from `.cedar`.
        """
        s3_bucket = metadata.get('s3_bucket')
        s3_key = metadata.get('s3_key')
        if not s3_bucket or not s3_key:
            raise PolicyNotFoundError(
                f"Policy metadata missing S3 reference for agent {agent_id}"
            )
        policy_obj = self.s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        policy_content = policy_obj['Body'].read().decode('utf-8')
        policy_data = yaml.safe_load(policy_content)

        # Cloud-from-agent (§2.3 / R7): override the policy's embedded cloud
        # identity with the AGENT's authoritative values. Keeps a shared policy
        # safe across clouds — binding any policy to any agent resolves THAT
        # agent's cloud. Fallback chain never errors on a missing field.
        policy_data['platform'] = agent.get('platform') or policy_data.get('platform')
        policy_data['cloud_region'] = resolve_cloud_region(agent, policy_data)

        logger.debug(
            f"Loaded policy {metadata.get('policy_id')} for {agent_id} "
            f"(platform={policy_data['platform']}, "
            f"cloud_region={policy_data['cloud_region']})"
        )
        return policy_data

    async def resolve_policy_bundle(self, agent_id: str) -> tuple[Dict, Dict, Dict]:
        """Resolve the full bundle the Cedar loader (CT06) needs in one place:
        `(structured_policy, metadata, agent_record)`. Keeps binding resolution +
        cloud-from-agent stamping identical to `get_agent_policy`.

        Raises PolicyDisabledError / PolicyNotFoundError like `get_agent_policy`.

        Hot-path cache (WS24 M3.5): the ALLOW path resolves this bundle up to 3×
        per request. The successful result is cached per (tenant, agent) for
        `policy_cache_ttl_seconds`, so the 2 DDB reads + 1 S3 GET run once, not
        three times. Errors are never cached. Invalidate on policy CRUD via
        `invalidate_policy_cache`; cross-instance staleness is TTL-bounded
        (consistent with the existing policy/agent metadata caches — fleet-wide
        invalidation is WS24 M3.2).

        ⚠️ The returned (policy_data, metadata, agent) tree is a SHARED cache
        reference. Callers MUST treat it as READ-ONLY — mutating any of these
        dicts poisons the cache for every subsequent request in the TTL window.
        Today's consumers (Cedar loader, context, abuse) are read-only.
        """
        cache_key = self._bundle_cache_key(agent_id)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Offload the synchronous boto3 chain (2 DDB + 1 S3) off the event
            # loop so concurrent validations don't serialize on it (WS24 M4.3).
            # asyncio.to_thread copies the contextvars Context, so tenancy stays
            # correct inside the worker thread.
            bundle = await asyncio.to_thread(self._resolve_bundle_sync, agent_id)
        except PolicyNotFoundError:
            raise
        except ClientError as e:
            logger.exception(f"AWS error loading policy for {agent_id}")
            raise PolicyNotFoundError(f"Failed to load policy: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error loading policy for {agent_id}")
            raise PolicyNotFoundError(f"Unexpected error: {e}")

        self.cache.set(cache_key, bundle, ttl=settings.policy_cache_ttl_seconds)
        return bundle

    def _resolve_bundle_sync(self, agent_id: str) -> tuple[Dict, Dict, Dict]:
        """Synchronous bundle resolution (2 DDB reads + 1 S3 GET). Wrapped in
        `asyncio.to_thread` by `resolve_policy_bundle` (WS24 M4.3)."""
        agent = self._get_agent_record(agent_id)
        metadata = self._resolve_policy_metadata(agent_id, agent)
        policy_data = self._load_structured_policy(agent_id, agent, metadata)
        return policy_data, metadata, agent

    @staticmethod
    def _bundle_cache_key(agent_id: str) -> str:
        # Tenant-scoped to prevent cross-tenant policy bleed on the shared cache.
        return f"policy_bundle:{tenancy.current_tenant()}:{agent_id}"

    def invalidate_policy_cache(self, agent_id: Optional[str] = None) -> None:
        """Drop cached bundle(s) so a policy change takes effect immediately on
        this instance (other instances expire via TTL — WS24 M3.5). Pass an
        `agent_id` to evict one agent, or omit it to evict the current tenant's
        whole policy-bundle family (use on policy create/update/delete/bind)."""
        if agent_id is not None:
            self.cache.invalidate(self._bundle_cache_key(agent_id))
        else:
            self.cache.invalidate_prefix(f"policy_bundle:{tenancy.current_tenant()}:")

    async def get_agent_policy(self, agent_id: str) -> Dict:
        """
        Resolve the agent's governing policy via its BINDING and load it
        (hybrid DynamoDB metadata + S3 content).

        Returns:
            Policy dict (allowed_tools, allowed_agents, policies, ...), with
            platform/cloud_region overridden to the agent's authoritative values.
            Return type is UNCHANGED — its 4 enforcement consumers
            (cross_agent/context/abuse/validation_service) keep the structured
            dict; the Cedar surface is exposed separately via resolve_policy_bundle
            + the Cedar loader (CT06), never by swapping this return type.

        Raises:
            PolicyDisabledError: bound policy exists but is disabled.
            PolicyNotFoundError: no binding (post-migration) / no fallback policy /
                missing S3 reference.
        """
        policy_data, _metadata, _agent = await self.resolve_policy_bundle(agent_id)
        return policy_data
    
    @stamps(Source.SENTRA_POLICY)
    async def validate(self, request: ValidationRequest) -> ValidationResult:
        """RETIRED (CT11) — fail-secure floor only.

        The hardcoded per-tool authorization checks (allowed_tools, process_refund
        cap, verify_identity fraud gate, invoke_agent) this method used to run were
        REMOVED when CedarPolicyEngine became the authoritative policy engine
        (feature: cedar-policy; dev cutover 2026-06-13). The structured-dict LOADER
        (get_agent_policy / resolve_policy_bundle / get_agent_cloud_identity) is
        unchanged — Cedar and the cross-agent/context/abuse consumers still use it.

        This method is now reachable ONLY when Cedar cannot decide (cedar disabled,
        or an agent with no Cedar artifact). There is no legacy engine to fall back
        to, so it FAILS SECURE (deny). It still resolves cloud identity for the audit
        stamp and preserves the POLICY_DISABLED / POLICY_NOT_FOUND reasons so those
        operator-actionable cases stay distinct.
        """
        platform, cloud_region = self.get_agent_cloud_identity(request.agent_id)
        try:
            policy = await self.get_agent_policy(request.agent_id)
            # Prefer the policy's stamped cloud identity (agent-sourced, §2.3)
            # over the pre-load registry read for the audit stamp.
            platform = policy.get("platform") or platform
            cloud_region = policy.get("cloud_region") or cloud_region
        except PolicyDisabledError:
            return ValidationResult(
                decision="DENY",
                reason=f"Policy for agent {request.agent_id} is disabled",
                violation_type="POLICY_DISABLED", penalty=-15, should_deny=True,
                platform=platform, cloud_region=cloud_region,
            )
        except PolicyNotFoundError:
            return ValidationResult(
                decision="DENY",
                reason=f"No policy found for agent {request.agent_id}",
                violation_type="POLICY_NOT_FOUND", penalty=-15, should_deny=True,
                platform=platform, cloud_region=cloud_region,
            )
        except Exception:
            logger.exception(f"Policy load error for agent {request.agent_id}")
        # Policy resolves, but legacy authorization is retired — fail secure.
        return ValidationResult(
            decision="DENY",
            reason="Legacy policy engine retired; Cedar is the authoritative authorization engine",
            violation_type="POLICY_ERROR", penalty=-15, should_deny=True,
            platform=platform, cloud_region=cloud_region,
        )
