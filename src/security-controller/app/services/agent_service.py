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
import logging
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import boto3
import yaml
from botocore.exceptions import ClientError

from app.config import settings
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

        # Tables (only for agent/tool/policy metadata - NOT sessions)
        self.agent_registry_table = self.dynamodb.Table(settings.dynamodb_agent_registry_table)
        self.tool_registry_table = self.dynamodb.Table(settings.dynamodb_tool_registry_table)
        self.policies_metadata_table = self.dynamodb.Table(settings.dynamodb_policies_metadata_table)

        # Session management (use SessionManager for consistency)
        self.session_manager = SessionManager()

        # Cache manager
        self.cache = get_cache_manager()
        self.cache_ttl = settings.agent_metadata_cache_ttl_seconds

        # Metrics namespace
        self.metrics_namespace = "AgentManagementAPI"
    
    async def list_agents(self, enrich: bool = True) -> Dict:
        """
        List all agents with optional runtime statistics.
        
        Args:
            enrich: If True (default), include runtime stats (ECS, CloudWatch, sessions).
                    Set to False for fast response (DynamoDB only).
        
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
            cache_key = f"agents_list_enrich_{enrich}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached agents list (enrich={enrich})")
                cache_hit = True
                self._publish_metrics("GetAgents", time.time() - start_time, cache_hit)
                return cached_data
            
            # Load agent metadata from DynamoDB with pagination support
            logger.info("Loading agents from sentra-agent-registry")
            agents = []
            last_evaluated_key = None
            
            # Paginate through all results (handles tables with >1MB of data)
            while True:
                if last_evaluated_key:
                    response = self.agent_registry_table.scan(
                        ExclusiveStartKey=last_evaluated_key
                    )
                else:
                    response = self.agent_registry_table.scan()
                
                agents.extend(response.get('Items', []))
                
                # Check if there are more pages
                last_evaluated_key = response.get('LastEvaluatedKey')
                if not last_evaluated_key:
                    break
            
            logger.debug(f"Loaded {len(agents)} agents from DynamoDB")

            # WS-21 D1/T05: show agents from ALL cloud providers (no platform/
            # bedrock exclusion). Only hide internal control-plane infra
            # (visibility == 'internal'), kept as a defense-in-depth safety net
            # alongside not registering the security-controller as an agent (T07).
            agents = [agent for agent in agents if agent.get('visibility', 'external') != 'internal']
            logger.debug(f"Filtered to {len(agents)} customer-facing agents (excluded visibility=internal)")

            # Ensure every returned agent has a resolved cloud_provider (derive
            # from platform if the attribute is missing) so the API never emits a
            # value outside the documented enum (Kombai crash fix).
            from app.utils.cloud import resolve_cloud_provider
            for agent in agents:
                agent['cloud_provider'] = resolve_cloud_provider(agent)

            # Enrich if requested (default behavior for backward compatibility)
            if enrich:
                # Parallel enrichment using asyncio.gather for better performance
                import asyncio
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
    
    async def get_cloud_provider_distribution(self) -> Dict[str, Any]:
        """WS-21 T21: group active agents by hosting cloud_provider.

        Backs GET /v1/metrics/platform-distribution and the overview
        active_agents/clouds KPIs. Reuses list_agents (so the visibility=internal
        filter and registry source are applied consistently); counts only
        status=active agents.
        """
        listed = await self.list_agents(enrich=False)
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

    async def attach_policy(self, agent_id: str, policy_id: str) -> Dict[str, Any]:
        """WS-21 T33: attach a policy to an agent (stored as attached_policy_ids SS).

        Raises KeyError (→404) if agent or policy is missing, ValueError (→409)
        if already attached.
        """
        agent = self.agent_registry_table.get_item(Key={'agent_id': agent_id}).get('Item')
        if not agent:
            raise KeyError(f"agent {agent_id} not found")
        policy = self.policies_metadata_table.get_item(Key={'policy_id': policy_id}).get('Item')
        if not policy:
            raise KeyError(f"policy {policy_id} not found")
        if policy_id in set(agent.get('attached_policy_ids') or []):
            raise ValueError(f"policy {policy_id} already attached to {agent_id}")

        attached_at = datetime.utcnow().isoformat() + 'Z'
        self.agent_registry_table.update_item(
            Key={'agent_id': agent_id},
            UpdateExpression="SET updated_at = :u ADD attached_policy_ids :p",
            ExpressionAttributeValues={':u': attached_at, ':p': {policy_id}},
        )
        return {"agent_id": agent_id, "policy_id": policy_id,
                "status": "attached", "attached_at": attached_at}

    async def detach_policy(self, agent_id: str, policy_id: str) -> Dict[str, Any]:
        """WS-21 T33: detach a policy from an agent. KeyError (→404) if the agent
        is missing or the policy is not currently attached."""
        agent = self.agent_registry_table.get_item(Key={'agent_id': agent_id}).get('Item')
        if not agent:
            raise KeyError(f"agent {agent_id} not found")
        if policy_id not in set(agent.get('attached_policy_ids') or []):
            raise KeyError(f"policy {policy_id} not attached to {agent_id}")

        self.agent_registry_table.update_item(
            Key={'agent_id': agent_id},
            UpdateExpression="SET updated_at = :u DELETE attached_policy_ids :p",
            ExpressionAttributeValues={':u': datetime.utcnow().isoformat() + 'Z', ':p': {policy_id}},
        )
        return {"agent_id": agent_id, "policy_id": policy_id, "status": "detached"}

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
            response = self.agent_registry_table.get_item(Key={'agent_id': agent_id})
            
            if 'Item' not in response:
                logger.warning(f"Agent {agent_id} not found")
                return None
            
            agent = response['Item']
            
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

            # Step 1: Query metadata table using agent-index GSI
            metadata_response = self.policies_metadata_table.query(
                IndexName='agent-index',
                KeyConditionExpression='agent_id = :agent_id',
                FilterExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':agent_id': agent_id,
                    ':status': 'active'
                },
                Limit=1,
                ScanIndexForward=False  # Get latest version first
            )

            if not metadata_response.get('Items'):
                logger.warning(f"No active policy metadata found for agent {agent_id}")
                return {"agent_id": agent_id, "tools": [], "total": 0}

            metadata = metadata_response['Items'][0]

            # Step 2: Download full policy YAML from S3
            s3_bucket = metadata.get('s3_bucket')
            s3_key = metadata.get('s3_key')

            if not s3_bucket or not s3_key:
                logger.error(f"Policy metadata missing S3 reference for agent {agent_id}")
                return {"agent_id": agent_id, "tools": [], "total": 0}

            policy_obj = self.s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            policy_content = policy_obj['Body'].read().decode('utf-8')

            # Step 3: Parse YAML and extract allowed_tools
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
        
        # Get active sessions count
        active_sessions = await self._get_active_sessions_count(agent_id)
        agent['active_sessions'] = active_sessions
        
        # Get average trust score
        avg_trust = await self._get_avg_trust_score(agent_id)
        agent['trust_score_avg'] = avg_trust
        
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
    
    async def _get_active_sessions_count(self, agent_id: str) -> int:
        """
        Get count of active sessions for an agent.

        Delegates to SessionManager for consistency and efficiency.

        Args:
            agent_id: Agent identifier

        Returns:
            Count of active sessions
        """
        return await self.session_manager.get_active_sessions_count(agent_id)

    async def _get_avg_trust_score(self, agent_id: str) -> float:
        """
        Get average trust score for an agent's sessions.

        Delegates to SessionManager for consistency with trust score logic.

        Args:
            agent_id: Agent identifier

        Returns:
            Average trust score (0-100)
        """
        return await self.session_manager.get_avg_trust_score(agent_id)
    
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
            metadata_response = self.policies_metadata_table.query(
                IndexName='agent-index',
                KeyConditionExpression='agent_id = :agent_id',
                FilterExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':agent_id': agent_id,
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
