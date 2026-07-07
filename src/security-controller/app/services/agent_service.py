"""
Agent Service - Agent Management Business Logic

Aggregates agent metadata from multiple sources:
- DynamoDB: Agent registry (metadata)
- ECS: Service status (running/stopped)
- CloudWatch Logs: Request counts (last 24h)
- Session Context: Active sessions and trust scores (via SessionManager)

Requirements: LLD 05 Section 3.1, 3.2, 3.3
Task 10: CloudWatch Metrics and Alarms
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import boto3
import yaml
from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy
from app.validators.cedar import policy_artifact
from app.utils.cache_manager import get_cache_manager
from app.utils.session_manager import SessionManager

logger = logging.getLogger(__name__)


# Human-readable labels for the cloud-provider distribution widget (WS-21 T21).
_PROVIDER_LABELS = {"aws": "AWS", "gcp": "GCP", "azure": "Azure", "unknown": "Unknown"}


def _compute_provider_breakdown(counts: Dict[str, int], total: int) -> List[Dict[str, Any]]:
    """Build [{cloud_provider, label, count, pct}] with integer pcts summing to 100.

    Largest bucket absorbs the rounding remainder so the pie always totals 100%.
    """
    if total <= 0:
        return []
    rows = []
    for provider, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        rows.append({
            "cloud_provider": provider,
            "label": _PROVIDER_LABELS.get(provider, provider.upper()),
            "count": count,
            "pct": int(count * 100 // total),  # floor first; fix remainder below
        })
    remainder = 100 - sum(r["pct"] for r in rows)
    if remainder and rows:
        rows[0]["pct"] += remainder  # largest bucket (rows sorted desc) takes it
    return rows


class AgentServiceError(Exception):
    """Raised when agent service operations fail"""
    pass


class AgentService:
    """
    Handles agent metadata aggregation and queries.
    
    Provides:
    - List all agents with runtime statistics
    - Get specific agent details
    - Get agent's allowed tools
    
    Metrics (Task 10):
    - AgentManagementAPI/GetAgents/Count
    - AgentManagementAPI/GetAgents/Latency
    - AgentManagementAPI/CacheHitRate
    """
    
    def __init__(self):
        self.region = settings.aws_region
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        self.ecs_client = boto3.client('ecs', region_name=self.region)
        self.logs_client = boto3.client('logs', region_name=self.region)
        self.cloudwatch = boto3.client('cloudwatch', region_name=self.region)
        self.s3_client = boto3.client('s3', region_name=self.region)

        # Tool registry is not tenant-scoped in M0a (platform-global); bind once.
        self.tool_registry_table = self.dynamodb.Table(settings.dynamodb_tool_registry_table)

        # Session management (use SessionManager for consistency)
        self.session_manager = SessionManager()

        # Cache manager
        self.cache = get_cache_manager()
        self.cache_ttl = settings.agent_metadata_cache_ttl_seconds

        # Metrics namespace
        self.metrics_namespace = "AgentManagementAPI"

    # Agent registry + policies-metadata are resolved per-call so the
    # TENANCY_V2_ENABLED flag is honored live (workstream T7). Table() is a
    # cheap name-binding, so re-resolving per access costs nothing.
    @property
    def agent_registry_table(self):
        return self.dynamodb.Table(tenancy.table_name('agent_registry'))

    @property
    def policies_metadata_table(self):
        return self.dynamodb.Table(tenancy.table_name('policies_metadata'))

    def _scan_all_agents_sync(self, fleet: bool = False) -> List[Dict]:
        """Paginated tenant-scoped scan of the agent registry (synchronous boto3).

        Extracted so :meth:`list_agents` can run it via ``asyncio.to_thread`` —
        the raw ``query_or_scan`` loop otherwise blocks the sole event loop.

        Args:
            fleet: When True, use ``fleet_scan`` (cross-tenant, for platform
                   operators' fleet KPIs). When False (default), use
                   ``query_or_scan`` (scoped to ``current_tenant()``).
        """
        scan_fn = tenancy.fleet_scan if fleet else tenancy.query_or_scan
        agents: List[Dict] = []
        last_evaluated_key = None
        registry_table = self.agent_registry_table
        while True:
            if last_evaluated_key:
                response = scan_fn(
                    registry_table, ExclusiveStartKey=last_evaluated_key
                )
            else:
                response = scan_fn(registry_table)
            agents.extend(response.get('Items', []))
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        return agents

    async def list_agents(self, enrich: bool = True, managed_only: bool = False, fleet: bool = False) -> Dict:
        """
        List all agents with optional runtime statistics.

        Args:
            enrich: If True (default), include runtime stats (ECS, CloudWatch, sessions).
                    Set to False for fast response (DynamoDB only).
            fleet: If True, scan ALL tenants (platform fleet view via fleet_scan).
                   Default False = scoped to current_tenant() via query_or_scan.

        Data Sources:
        1. Agent metadata from sentra-agent-registry table (Scan with pagination)
        2. (If enrich=True) Runtime stats from ECS API, CloudWatch Logs, sessions

        Returns:
            Dictionary with agents array and total count
        """
        start_time = time.time()
        cache_hit = False

        try:
            # Check cache first (separate cache keys for enriched vs non-enriched)
            cache_key = f"agents_list_enrich_{enrich}_managed_{managed_only}_fleet_{fleet}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached agents list (enrich={enrich})")
                cache_hit = True
                self._publish_metrics("GetAgents", time.time() - start_time, cache_hit)
                return cached_data
            
            # Load agent metadata from DynamoDB with pagination support.
            # The paginated scan is synchronous boto3 → run it on a worker thread
            # so it does not block the sole asyncio loop and serialize the
            # dashboard's concurrent reads (RCA 2026-07-02).
            logger.info("Loading agents from sentra-agent-registry")
            agents = await asyncio.to_thread(self._scan_all_agents_sync, fleet)

            logger.debug(f"Loaded {len(agents)} agents from DynamoDB")

            # WS-21 D1/T05: show agents from ALL cloud providers (no platform/
            # bedrock exclusion). Only hide internal control-plane infra
            # (visibility == 'internal'), kept as a defense-in-depth safety net
            # alongside not registering the security-controller as an agent (T07).
            agents = [agent for agent in agents if agent.get('visibility', 'external') != 'internal']
            logger.debug(f"Filtered to {len(agents)} customer-facing agents (excluded visibility=internal)")

            # feature §8.1: the Agent Inventory shows ONLY Managed agents — those
            # with observed /v1/validate traffic (data flowing). Imported-but-silent
            # agents stay in the Import tab. Signal-derived + sticky + last_active.
            # Opt-in (managed_only) so other callers of GET /v1/agents are unaffected.
            if managed_only:
                from app.utils import agent_activity
                signals_table = self.dynamodb.Table(tenancy.table_name('validation_signals'))
                active = agent_activity.last_active(signals_table, [a.get('agent_id') for a in agents])
                agents = [a for a in agents if a.get('agent_id') in active]
                for a in agents:
                    a['last_active'] = active.get(a.get('agent_id'))
                    a['lifecycle_status'] = 'managed'
                logger.debug(f"Filtered to {len(agents)} Managed agents (validate traffic observed)")

            # Ensure every returned agent has a resolved cloud_provider (derive
            # from platform if the attribute is missing) so the API never emits a
            # value outside the documented enum (Kombai crash fix).
            from app.utils.cloud import resolve_cloud_provider
            for agent in agents:
                agent['cloud_provider'] = resolve_cloud_provider(agent)

            # agent-policy-management §4.4/T22: surface active_policy_id (the
            # binding iff its policy is lifecycle-active). Batch-load all policy
            # statuses ONCE, then map — no per-agent lookup (D / no N+1).
            # Synchronous projected scan → worker thread (don't block the loop).
            status_map = await asyncio.to_thread(self._load_policy_status_map)
            for agent in agents:
                agent['active_policy_id'] = self._active_policy_id(
                    agent.get('attached_policy_id'), status_map.get(agent.get('attached_policy_id'))
                )

            # Enrich if requested (default behavior for backward compatibility)
            if enrich:
                # Parallel enrichment using asyncio.gather for better performance
                enrichment_tasks = [self._enrich_agent_metadata(agent) for agent in agents]
                enriched_results = await asyncio.gather(*enrichment_tasks, return_exceptions=True)
                
                # Process results, keeping original agent data on failure
                enriched_agents = []
                for i, result in enumerate(enriched_results):
                    if isinstance(result, Exception):
                        logger.warning(f"Failed to enrich agent {agents[i].get('agent_id')}: {result}")
                        enriched_agents.append(agents[i])
                    else:
                        enriched_agents.append(result)
                agents = enriched_agents
            
            result = {
                "agents": agents,
                "total": len(agents)
            }
            
            # Cache result (shorter TTL for non-enriched since it's fast anyway)
            cache_ttl = self.cache_ttl if enrich else 30
            self.cache.set(cache_key, result, ttl=cache_ttl)
            
            # Publish metrics
            self._publish_metrics("GetAgents", time.time() - start_time, cache_hit)
            
            return result
            
        except Exception as e:
            logger.exception("Error listing agents")
            # Publish error metric
            self._publish_error_metric("GetAgents", "SERVICE_ERROR")
            # Return empty array on error (fail-safe for Dashboard)
            return {"agents": [], "total": 0, "error": str(e)}
    
    async def get_cloud_provider_distribution(self, fleet: bool = False) -> Dict[str, Any]:
        """WS-21 T21: group active agents by hosting cloud_provider.

        Backs GET /v1/metrics/platform-distribution and the overview
        active_agents/clouds KPIs. Reuses list_agents (so the visibility=internal
        filter and registry source are applied consistently); counts only
        status=active agents.

        Args:
            fleet: When True, list_agents uses fleet_scan (cross-tenant) for the
                   platform fleet dashboard. Default False = tenant-scoped.
        """
        listed = await self.list_agents(enrich=False, fleet=fleet)
        agents = [a for a in listed.get('agents', []) if a.get('status') == 'active']

        counts: Dict[str, int] = {}
        for agent in agents:
            provider = agent.get('cloud_provider') or 'unknown'
            counts[provider] = counts.get(provider, 0) + 1

        total = sum(counts.values())
        return {
            "total_nodes": total,
            "clouds": len(counts),
            "providers": _compute_provider_breakdown(counts, total),
        }

    async def attach_policy(
        self, agent_id: str, policy_id: str, operator_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set the agent's policy BINDING (agent-policy-management §4.2 / T21).

        Writes the scalar `attached_policy_id` the engine reads — this REPLACES the
        previous vestigial String-Set write (WS-21 T33). Rebind-as-replace: an
        already-bound agent is swapped atomically in a single conditional
        update_item (no forced detach-first, no 409). The scalar SET is item-level
        atomic, so concurrent attaches can't interleave into a corrupt multi-value
        state the way the old String-Set ADD could. `operator_email` (when sent) is
        recorded as `last_updated_by` for binding audit attribution.

        Raises KeyError (→404) if the agent or policy is missing.
        """
        agent = self.agent_registry_table.get_item(Key=tenancy.item_key('agent_id', agent_id)).get('Item')
        if not agent:
            raise KeyError(f"agent {agent_id} not found")
        policy = self.policies_metadata_table.get_item(Key=tenancy.item_key('policy_id', policy_id)).get('Item')
        if not policy:
            raise KeyError(f"policy {policy_id} not found")

        attached_at = datetime.utcnow().isoformat() + 'Z'
        try:
            self.agent_registry_table.update_item(
                Key=tenancy.item_key('agent_id', agent_id),
                UpdateExpression="SET attached_policy_id = :p, updated_at = :u, last_updated_by = :who",
                ExpressionAttributeValues={
                    ':p': policy_id, ':u': attached_at, ':who': operator_email or 'unknown',
                },
                # Guard against a TOCTOU delete between the read above and the
                # write (the agent must still exist).
                ConditionExpression="attribute_exists(agent_id)",
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise KeyError(f"agent {agent_id} not found")
            raise
        self._invalidate_agent_cache(agent_id)
        return {"agent_id": agent_id, "policy_id": policy_id,
                "status": "attached", "attached_at": attached_at}

    async def detach_policy(
        self, agent_id: str, policy_id: str, operator_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Clear the agent's policy BINDING (agent-policy-management §4.2 / T21).

        Removes the scalar `attached_policy_id` only if it currently equals
        `policy_id` (ConditionExpression), so a detach can't race a concurrent
        rebind into clearing the wrong policy. `operator_email` (when sent) is
        recorded as `last_updated_by`. KeyError (→404) if the agent is missing or
        not currently bound to that policy.
        """
        agent = self.agent_registry_table.get_item(Key=tenancy.item_key('agent_id', agent_id)).get('Item')
        if not agent:
            raise KeyError(f"agent {agent_id} not found")
        if agent.get('attached_policy_id') != policy_id:
            raise KeyError(f"policy {policy_id} not attached to {agent_id}")

        try:
            self.agent_registry_table.update_item(
                Key=tenancy.item_key('agent_id', agent_id),
                UpdateExpression="REMOVE attached_policy_id SET updated_at = :u, last_updated_by = :who",
                ExpressionAttributeValues={
                    ':u': datetime.utcnow().isoformat() + 'Z',
                    ':who': operator_email or 'unknown',
                    ':current': policy_id,
                },
                ConditionExpression="attached_policy_id = :current",
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise KeyError(f"policy {policy_id} not attached to {agent_id}")
            raise
        self._invalidate_agent_cache(agent_id)
        return {"agent_id": agent_id, "policy_id": policy_id, "status": "detached"}

    def _invalidate_agent_cache(self, agent_id: str) -> None:
        """Best-effort local cache bust after a binding write so this task's
        subsequent reads reflect it. The cache manager only exposes clear()
        (no per-key delete), which is fine here — binding writes are rare and the
        agent/list entries are cheap to repopulate. Other tasks are TTL-bounded
        (agent-policy-management K7); no cross-task invalidation is claimed."""
        try:
            self.cache.clear()
        except Exception:  # cache is an optimization; never fail a write on it
            logger.debug("agent cache invalidation skipped", exc_info=True)

    async def get_agent(self, agent_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Agent dict with runtime statistics, or None if not found
        """
        start_time = time.time()
        cache_hit = False
        
        try:
            # Check cache first
            cache_key = f"agent:{agent_id}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached agent data for {agent_id}")
                cache_hit = True
                self._publish_metrics("GetAgent", time.time() - start_time, cache_hit)
                return cached_data
            
            # Load agent metadata from DynamoDB
            logger.info(f"Loading agent {agent_id} from sentra-agent-registry")
            response = self.agent_registry_table.get_item(Key=tenancy.item_key('agent_id', agent_id))
            
            if 'Item' not in response:
                logger.warning(f"Agent {agent_id} not found")
                return None
            
            agent = response['Item']

            # agent-policy-management §4.4/T22: active_policy_id = the binding iff
            # its policy is active. Single endpoint → one get_item on the bound id.
            from app.utils.cloud import resolve_cloud_provider
            agent['cloud_provider'] = resolve_cloud_provider(agent)
            bound = agent.get('attached_policy_id')
            bound_status = None
            if bound:
                bound_meta = self.policies_metadata_table.get_item(
                    Key=tenancy.item_key('policy_id', bound)
                ).get('Item')
                bound_status = (bound_meta or {}).get('status')
            agent['active_policy_id'] = self._active_policy_id(bound, bound_status)

            # Enrich with runtime statistics
            enriched_agent = await self._enrich_agent_metadata(agent)

            # Add allowed tools count
            tools_count = await self._get_agent_tools_count(agent_id)
            enriched_agent['allowed_tools_count'] = tools_count
            
            # Cache result
            self.cache.set(cache_key, enriched_agent, ttl=self.cache_ttl)
            
            # Publish metrics
            self._publish_metrics("GetAgent", time.time() - start_time, cache_hit)
            
            return enriched_agent
            
        except Exception as e:
            logger.exception(f"Error getting agent {agent_id}")
            self._publish_error_metric("GetAgent", "SERVICE_ERROR")
            return None
    
    def _load_policy_status_map(self) -> Dict[str, str]:
        """{policy_id: status} for every policy, via ONE projected Scan.

        agent-policy-management §4.4/T22 (Batch/D): the list endpoint maps each
        agent's binding to active_policy_id without an N+1 per-agent lookup. A
        Scan is the conscious MVP choice (~4 policies, trivial); it is wrong at
        scale — swap for BatchGetItem on the referenced ids when the policy set
        grows.
        """
        status_map: Dict[str, str] = {}
        metadata_table = self.policies_metadata_table
        kwargs = {"ProjectionExpression": "policy_id, #s",
                  "ExpressionAttributeNames": {"#s": "status"}}
        while True:
            resp = tenancy.query_or_scan(metadata_table, **kwargs)
            for item in resp.get("Items", []):
                pid = item.get("policy_id")
                if pid:
                    status_map[pid] = item.get("status")
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                return status_map
            kwargs["ExclusiveStartKey"] = lek

    @staticmethod
    def _active_policy_id(attached_policy_id: Optional[str], status: Optional[str]) -> Optional[str]:
        """The binding iff its policy is lifecycle-active, else None (§4.4).

        Binding-only by design: an UNBOUND agent reports null even if a legacy
        GSI policy would still resolve at enforcement time — the UI uses null to
        prompt 'Attach', nudging the operator onto the binding model.
        """
        if attached_policy_id and status == 'active':
            return attached_policy_id
        return None

    def _resolve_policy_metadata_for_agent(self, agent_id: str) -> Optional[Dict]:
        """Policy metadata for an agent via its binding, else the legacy GSI.

        agent-policy-management G1/T15 — mirrors PolicyEngine.get_agent_policy
        resolution so display paths (Agent Detail → Tools) agree with enforcement:
          1. read the agent's `attached_policy_id`; load that policy by stored id
             (never reconstructed, K2); require it lifecycle-active.
          2. no binding → fall back to the `agent-index` GSI (`status=active`).
        Returns the metadata Item, or None if nothing resolvable.
        """
        agent = self.agent_registry_table.get_item(
            Key=tenancy.item_key('agent_id', agent_id)
        ).get('Item') or {}
        bound_policy_id = agent.get('attached_policy_id')

        if bound_policy_id:
            meta = self.policies_metadata_table.get_item(
                Key=tenancy.item_key('policy_id', bound_policy_id)
            ).get('Item')
            # Bound but missing/disabled → no tools to show (matches the engine's
            # fail-secure DENY; the UI surfaces "no active policy").
            if not meta or meta.get('status') != 'active':
                return None
            return meta

        agent_kce, agent_val = tenancy.agent_index_kce_value(agent_id)
        resp = self.policies_metadata_table.query(
            IndexName='agent-index',
            KeyConditionExpression=agent_kce,
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':agent_id': agent_val, ':status': 'active'},
            Limit=1,
            ScanIndexForward=False,
        )
        items = resp.get('Items', [])
        return items[0] if items else None

    async def get_agent_tools(self, agent_id: str) -> Dict:
        """
        Get allowed tools for an agent.

        Data Sources (Hybrid Pattern - Data Model v2):
        1. sentra-policies-metadata table (query by agent_id using GSI)
        2. S3 (download full policy YAML using s3_key from metadata)
        3. sentra-tool-registry table (full tool metadata)

        Args:
            agent_id: Agent identifier

        Returns:
            Dictionary with tools array and total count
        """
        start_time = time.time()
        cache_hit = False

        try:
            # Check cache first
            cache_key = f"agent_tools:{agent_id}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached tools for agent {agent_id}")
                cache_hit = True
                self._publish_metrics("GetAgentTools", time.time() - start_time, cache_hit)
                return cached_data

            # Get allowed tool IDs using hybrid pattern (DynamoDB metadata + S3 content)
            logger.info(f"Loading allowed tools for agent {agent_id} using hybrid pattern")

            # Step 1: Resolve the agent's policy metadata via its BINDING so the
            # displayed tools match the ENFORCED policy (agent-policy-management
            # G1/T15). The engine resolves via attached_policy_id; this display
            # path must agree, else the Tools tab shows the GSI-authored policy's
            # tools after a different policy is bound. Falls back to the legacy
            # GSI during migration (§2.6).
            metadata = self._resolve_policy_metadata_for_agent(agent_id)
            if not metadata:
                logger.warning(f"No active policy metadata found for agent {agent_id}")
                return {"agent_id": agent_id, "tools": [], "total": 0}

            # Step 2: Download the STRUCTURED policy source from S3.
            #
            # CT06b/CT06c invariant: `s3_key` ALWAYS points at the structured
            # source (`…/v{version}.yaml`), even when `policy_format == 'cedar'`.
            # The compiled Cedar is a co-artifact at a derived `.cedar` key and is
            # NEVER what `s3_key` references. So `allowed_tools` for the Tools tab
            # is always read from the structured source — never from the `.cedar`
            # text (which isn't YAML and would break this path). We assert the key
            # is a structured-source extension so a future drift fails loud here
            # instead of silently returning an empty Tools tab.
            s3_bucket = metadata.get('s3_bucket')
            s3_key = metadata.get('s3_key')
            policy_format = metadata.get(policy_artifact.POLICY_FORMAT_FIELD, policy_artifact.FORMAT_YAML)

            if not s3_bucket or not s3_key:
                logger.error(f"Policy metadata missing S3 reference for agent {agent_id}")
                return {"agent_id": agent_id, "tools": [], "total": 0}

            if s3_key.endswith(policy_artifact.CEDAR_EXT):
                # s3_key must address the structured source, not the compiled Cedar.
                logger.error(
                    f"Agent {agent_id} s3_key {s3_key!r} points at compiled Cedar, "
                    f"not the structured source (policy_format={policy_format}); "
                    f"refusing to YAML-parse it"
                )
                return {"agent_id": agent_id, "tools": [], "total": 0}

            policy_obj = self.s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            policy_content = policy_obj['Body'].read().decode('utf-8')

            # Step 3: Parse the structured source and extract allowed_tools.
            policy_data = yaml.safe_load(policy_content)
            allowed_tool_ids = policy_data.get('allowed_tools', [])

            logger.debug(f"Loaded {len(allowed_tool_ids)} allowed tools from S3: {s3_key}")

            # Step 4: Get full tool metadata from sentra-tool-registry
            tools = []
            for tool_id in allowed_tool_ids:
                try:
                    tool_response = self.tool_registry_table.get_item(Key={'tool_id': tool_id})
                    if 'Item' in tool_response:
                        tools.append(tool_response['Item'])
                    else:
                        logger.warning(f"Tool {tool_id} not found in registry for agent {agent_id}")
                except Exception as e:
                    logger.warning(f"Error loading tool {tool_id}: {e}")
                    continue

            result = {
                "agent_id": agent_id,
                "tools": tools,
                "total": len(tools)
            }

            # Cache result (tools change rarely)
            self.cache.set(cache_key, result, ttl=settings.tool_registry_cache_ttl_seconds)

            # Publish metrics
            self._publish_metrics("GetAgentTools", time.time() - start_time, cache_hit)

            return result

        except Exception as e:
            logger.exception(f"Error getting tools for agent {agent_id}")
            self._publish_error_metric("GetAgentTools", "SERVICE_ERROR")
            return {"agent_id": agent_id, "tools": [], "total": 0, "error": str(e)}
    
    async def _enrich_agent_metadata(self, agent: Dict) -> Dict:
        """
        Enrich agent metadata with runtime statistics.
        
        Args:
            agent: Base agent metadata from DynamoDB
            
        Returns:
            Enriched agent dict with runtime stats
        """
        agent_id = agent.get('agent_id')
        
        # Get ECS service status
        ecs_status = await self._get_ecs_status(agent.get('ecs_config', {}).get('service_name'))
        agent['status'] = ecs_status.get('status', 'unknown')
        agent['uptime_seconds'] = ecs_status.get('uptime_seconds', 0)
        agent['last_seen'] = ecs_status.get('last_seen')
        
        # Get request counts from CloudWatch Logs (last 24h)
        request_counts = await self._get_request_counts(agent_id)
        agent['requests_total'] = request_counts.get('total', 0)
        agent['requests_allowed'] = request_counts.get('allowed', 0)
        agent['requests_denied'] = request_counts.get('denied', 0)
        
        # Session-derived stats (active count + avg trust) in ONE indexed Query
        # on agent-updated-index — was two full-table scans per agent (WS-21 C5/T50).
        stats = await self.session_manager.get_agent_session_stats(agent_id)
        agent['active_sessions'] = stats['active_sessions']
        agent['trust_score_avg'] = stats['avg_trust_score']

        return agent
    
    async def _get_ecs_status(self, service_name: Optional[str]) -> Dict:
        """
        Get ECS service status.
        
        Args:
            service_name: ECS service name
            
        Returns:
            Dict with status, uptime_seconds, last_seen
        """
        if not service_name:
            return {
                'status': 'unknown',
                'uptime_seconds': 0,
                'last_seen': None
            }
        
        try:
            # Describe ECS service
            response = self.ecs_client.describe_services(
                cluster='sentra-mvp-cluster',
                services=[service_name]
            )
            
            if not response.get('services'):
                return {
                    'status': 'not_found',
                    'uptime_seconds': 0,
                    'last_seen': None
                }
            
            service = response['services'][0]
            
            # Determine status
            desired_count = service.get('desiredCount', 0)
            running_count = service.get('runningCount', 0)
            
            if running_count > 0:
                status = 'running'
            elif desired_count > 0:
                status = 'starting'
            else:
                status = 'stopped'
            
            # Calculate uptime (approximate from createdAt)
            created_at = service.get('createdAt')
            uptime_seconds = 0
            if created_at:
                uptime_seconds = int((datetime.now(created_at.tzinfo) - created_at).total_seconds())
            
            return {
                'status': status,
                'uptime_seconds': uptime_seconds,
                'last_seen': datetime.utcnow().isoformat() + 'Z'
            }
            
        except Exception as e:
            logger.warning(f"Error getting ECS status for {service_name}: {e}")
            return {
                'status': 'unknown',
                'uptime_seconds': 0,
                'last_seen': None
            }
    
    async def _get_request_counts(self, agent_id: str) -> Dict:
        """
        Get request counts from CloudWatch Logs (last 24h) filtered by agent_id.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Dict with total, allowed, denied counts
        """
        try:
            from datetime import datetime, timedelta
            
            # Calculate time range (last 24h)
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)
            
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)
            
            # Query CloudWatch Logs Insights for this agent
            query = f'''
            fields @timestamp, decision
            | filter agent_id = "{agent_id}"
            | stats count() by decision
            '''
            
            response = self.logs_client.start_query(
                logGroupName=settings.cloudwatch_log_group,
                startTime=start_ms,
                endTime=end_ms,
                queryString=query
            )
            
            query_id = response['queryId']
            
            # Wait for query to complete (max 5 seconds)
            import asyncio
            for _ in range(10):
                await asyncio.sleep(0.5)
                result = self.logs_client.get_query_results(queryId=query_id)
                if result['status'] == 'Complete':
                    break
            
            # Parse results
            allowed = 0
            denied = 0
            
            if result['status'] == 'Complete':
                for row in result.get('results', []):
                    decision = None
                    count = 0
                    for field in row:
                        if field['field'] == 'decision':
                            decision = field['value']
                        elif field['field'] == 'count()':
                            count = int(field['value'])
                    
                    if decision == 'ALLOW':
                        allowed = count
                    elif decision == 'DENY':
                        denied = count
            
            total = allowed + denied
            
            return {
                'total': total,
                'allowed': allowed,
                'denied': denied
            }
            
        except Exception as e:
            logger.warning(f"Error getting request counts for {agent_id}: {e}")
            return {'total': 0, 'allowed': 0, 'denied': 0}
    
    async def _get_agent_tools_count(self, agent_id: str) -> int:
        """
        Get count of allowed tools for an agent using hybrid pattern.

        Args:
            agent_id: Agent identifier

        Returns:
            Count of allowed tools
        """
        try:
            # Query metadata table using agent-index GSI
            agent_kce, agent_val = tenancy.agent_index_kce_value(agent_id)
            metadata_response = self.policies_metadata_table.query(
                IndexName='agent-index',
                KeyConditionExpression=agent_kce,
                FilterExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':agent_id': agent_val,
                    ':status': 'active'
                },
                Limit=1,
                ScanIndexForward=False
            )

            if not metadata_response.get('Items'):
                return 0

            # Use cached count from metadata (no need to download full S3 file)
            metadata = metadata_response['Items'][0]
            return metadata.get('allowed_tools_count', 0)

        except Exception as e:
            logger.warning(f"Error getting tools count for {agent_id}: {e}")
            return 0
    
    def _publish_metrics(self, operation: str, latency_ms: float, cache_hit: bool):
        """
        Publish CloudWatch metrics for Agent Management API operations.
        
        Args:
            operation: Operation name (GetAgents, GetAgent, GetAgentTools)
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
    
    def _publish_error_metric(self, operation: str, error_type: str):
        """
        Publish error metric for Agent Management API operations.
        
        Args:
            operation: Operation name
            error_type: Type of error
        
        Note: Fire-and-forget. Metrics failures don't block operations.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.metrics_namespace,
                MetricData=[
                    {
                        'MetricName': f'{operation}/Errors',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'ErrorType', 'Value': error_type}
                        ]
                    }
                ]
            )
            
            logger.debug(f"Published error metric for {operation}: {error_type}")
            
        except Exception as e:
            logger.warning(f"Failed to publish error metric (non-blocking): {e}")
