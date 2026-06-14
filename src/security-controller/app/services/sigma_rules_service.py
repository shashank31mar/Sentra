"""
Sigma Rules Service - Sigma Rule Management Business Logic

Queries Sigma rules with filters and enriches with match statistics.

Data Sources:
- DynamoDB: sentra-sigma-rules-metadata (metadata with match stats)
- S3: Full Sigma rule YAML content (on-demand)

Requirements: LLD 05 Section 3.5
Task 10: CloudWatch Metrics and Alarms
"""
import logging
import time
from typing import Dict, List, Optional

import boto3
from boto3.dynamodb.types import Decimal as DDBDecimal  # boto3.dynamodb is NOT auto-loaded; must import explicitly
import yaml
from botocore.exceptions import ClientError

from app.config import settings
from app.utils.cache_manager import get_cache_manager
from app.utils.pagination import decode_cursor, next_token_from_response

logger = logging.getLogger(__name__)


# The console (LLD 21 SigmaRule DTO) speaks enabled/disabled + severity + match_count.
# DynamoDB stores the Sigma-native vocabulary: status=stable|experimental|deprecated and
# level=critical|high|medium|low, with match counts nested under `stats`. Only `stable` rules
# are actually loaded into the detection engine, so `stable` => enabled and everything else
# (experimental/deprecated) => disabled, which makes the console toggle reflect real enforcement.
_DDB_STATUS_ENABLED = "stable"
_DDB_STATUS_DISABLED = "deprecated"


def _enabled_to_ddb_status(api_status: str) -> Optional[str]:
    """Translate the console's enabled/disabled toggle to the stored Sigma status.

    Accepts the native stored values too (stable/deprecated) for backward compatibility.
    Returns None for anything unrecognized so the caller can 400.
    """
    mapping = {
        "enabled": _DDB_STATUS_ENABLED,
        "disabled": _DDB_STATUS_DISABLED,
        "stable": _DDB_STATUS_ENABLED,
        "deprecated": _DDB_STATUS_DISABLED,
    }
    return mapping.get((api_status or "").strip().lower())


def _derive_category(rule: Dict) -> str:
    """Pick a human-ish category for the console from the rule's tags/logsource.

    Sigma rules don't have a first-class 'category' in our metadata; prefer the first
    attack.*/owasp.* tag, else the logsource category, else a sane default.
    """
    tags = rule.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            tag_str = str(tag)
            if tag_str.startswith(("attack.", "owasp.")):
                # e.g. "attack.llm01" -> "llm01"; "owasp.llm.top10.2025" -> "llm"
                return tag_str.split(".", 1)[1].split(".", 1)[0]
        if tags:
            return str(tags[0])
    logsource = rule.get("logsource")
    if isinstance(logsource, dict) and logsource.get("category"):
        return str(logsource["category"])
    return "detection"


def _to_api_rule(rule: Dict, match_count: Optional[int] = None) -> Dict:
    """Map a raw DDB sigma metadata item to the console's SigmaRule contract.

    enabled/disabled status, flat severity, flat match_count, derived category.
    Unknown/extra fields are dropped — the console only renders these.

    match_count comes from CloudWatch (the SigmaRuleMatches metric, per RuleId),
    passed in by the caller. The DDB ``stats.match_count_*`` fields are DEAD —
    they were never incremented at runtime (the only writer,
    update_rule_match_count(), is called by nothing but tests), so they sit at
    their seeded 0 forever. We intentionally do NOT read them here. If CloudWatch
    has no series for a rule yet (it never matched, or matched before emission
    shipped), the count is 0.
    """
    if match_count is None:
        match_count = 0
    try:
        match_count = int(match_count)
    except (TypeError, ValueError):
        match_count = 0

    # patterns_count lives flat on the DDB item (written by the seed script).
    patterns_count = rule.get("patterns_count", 0)
    try:
        patterns_count = int(patterns_count)
    except (TypeError, ValueError):
        patterns_count = 0

    ddb_status = (rule.get("status") or "").strip().lower()
    return {
        "rule_id": rule.get("rule_id"),
        "title": rule.get("title") or rule.get("rule_id"),
        "description": rule.get("description", ""),
        "category": _derive_category(rule),
        "severity": rule.get("level") or "medium",
        "status": "enabled" if ddb_status == _DDB_STATUS_ENABLED else "disabled",
        "patterns_count": patterns_count,
        "match_count": match_count,
    }


class SigmaRulesServiceError(Exception):
    """Raised when Sigma rules service operations fail"""
    pass


class SigmaRulesService:
    """
    Handles Sigma rule queries and metadata aggregation.
    
    Provides:
    - List Sigma rules with filters (status, level)
    - Sort by match count (most active first)
    - Cache results for performance
    
    Note: Returns metadata only (not full YAML content).
    Dashboard can fetch full content from S3 on-demand if needed.
    
    Metrics (Task 10):
    - AgentManagementAPI/GetSigmaRules/Count
    - AgentManagementAPI/GetSigmaRules/Latency
    - AgentManagementAPI/CacheHitRate
    """
    
    def __init__(self):
        self.region = settings.aws_region
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        self.s3_client = boto3.client('s3', region_name=self.region)
        self.cloudwatch = boto3.client('cloudwatch', region_name=self.region)
        
        # Tables
        self.sigma_rules_metadata_table = self.dynamodb.Table(settings.dynamodb_sigma_rules_metadata_table)
        
        # Cache manager
        self.cache = get_cache_manager()
        self.cache_ttl = settings.sigma_rules_metadata_cache_ttl_seconds
        
        # Metrics namespace
        self.metrics_namespace = "AgentManagementAPI"

    def _get_match_counts(self, match_range: str) -> Dict[str, int]:
        """Per-rule Sigma match counts from CloudWatch for the given window.

        Delegates to MetricsQueryService.sigma_match_counts (reads the
        SigmaRuleMatches metric, per RuleId). Returns {} on any error so the
        rule list still renders with zeroed counts rather than failing.
        """
        try:
            from app.services.metrics_query_service import MetricsQueryService
            return MetricsQueryService(self.cloudwatch).sigma_match_counts(match_range)
        except Exception as e:
            logger.warning(f"Could not load Sigma match counts from CloudWatch: {e}")
            return {}
    
    async def list_sigma_rules(
        self,
        status: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        match_range: str = "24h"
    ) -> Dict:
        """
        List Sigma rules from DynamoDB metadata table with filters.
        
        Data Source: sentra-sigma-rules-metadata table
        Note: Returns metadata only. Full rule content in S3, loaded on-demand.

        Match counts are sourced from CloudWatch (the SigmaRuleMatches metric,
        per RuleId) for the requested ``match_range`` window — NOT from the dead
        DDB ``stats.match_count_*`` fields.

        Args:
            status: Filter by status (stable/experimental/deprecated) (optional)
            level: Filter by severity level (critical/high/medium/low) (optional)
            limit: Max results (default: 50, max: 200)
            match_range: Time window for match counts (1h/24h/7d/30d, default 24h)
            
        Returns:
            Dictionary with rules array, total, and has_more flag
        """
        start_time = time.time()
        cache_hit = False
        
        try:
            # Build cache key (cursor + match_range included so pages/windows don't collide)
            cache_key = f"sigma_rules:status={status}:level={level}:limit={limit}:cursor={cursor}:range={match_range}"
            start_key = decode_cursor(cursor) if cursor else None
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached Sigma rules for {cache_key}")
                cache_hit = True
                self._publish_metrics("GetSigmaRules", time.time() - start_time, cache_hit)
                return cached_data
            
            # Cap limit
            limit = min(limit, 200)
            
            # Query DynamoDB based on filters
            rules = []
            
            if status:
                # Use status-index GSI
                logger.info(f"Querying Sigma rules with status: {status}")
                response = self.sigma_rules_metadata_table.query(
                    IndexName='status-index',
                    KeyConditionExpression='#status = :status',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={':status': status},
                    Limit=limit,
                    **({"ExclusiveStartKey": start_key} if start_key else {})
                )
                rules = response.get('Items', [])
                
            elif level:
                # Use level-index GSI
                logger.info(f"Querying Sigma rules with level: {level}")
                response = self.sigma_rules_metadata_table.query(
                    IndexName='level-index',
                    KeyConditionExpression='#level = :level',
                    ExpressionAttributeNames={'#level': 'level'},
                    ExpressionAttributeValues={':level': level},
                    Limit=limit,
                    **({"ExclusiveStartKey": start_key} if start_key else {})
                )
                rules = response.get('Items', [])
                
            else:
                # Scan all rules (no filters)
                logger.info("Scanning all Sigma rules")
                response = self.sigma_rules_metadata_table.scan(
                    Limit=limit,
                    **({"ExclusiveStartKey": start_key} if start_key else {})
                )
                rules = response.get('Items', [])
            
            # Apply additional filters if both status and level provided
            if status and level:
                rules = [r for r in rules if r.get('level') == level]

            # Fetch per-rule match counts from CloudWatch for the requested
            # window. This is the real source of truth — the DDB
            # stats.match_count_* fields are dead (never incremented at runtime).
            # On any CloudWatch error we fall back to an empty map (counts -> 0)
            # so the rule list still renders; the count column just shows 0.
            match_counts = self._get_match_counts(match_range)

            # Sort by CloudWatch match count (most active first).
            rules.sort(
                key=lambda r: match_counts.get(r.get('rule_id'), 0),
                reverse=True
            )

            result = {
                "rules": [
                    _to_api_rule(r, match_counts.get(r.get('rule_id'), 0))
                    for r in rules[:limit]
                ],
                "total": len(rules),
                "next_token": next_token_from_response(response),
            }
            
            # Cache result
            self.cache.set(cache_key, result, ttl=self.cache_ttl)
            
            # Publish metrics
            self._publish_metrics("GetSigmaRules", time.time() - start_time, cache_hit)
            
            return result
            
        except Exception as e:
            logger.exception("Error listing Sigma rules")
            # Return empty array on error (fail-safe for Dashboard)
            return {"rules": [], "total": 0, "next_token": None, "error": str(e)}
    
    async def get_sigma_rule(self, rule_id: str) -> Optional[Dict]:
        """
        Get specific Sigma rule by ID (metadata only).
        
        Args:
            rule_id: Sigma rule identifier
            
        Returns:
            Rule metadata dict, or None if not found
        """
        try:
            # Check cache first
            cache_key = f"sigma_rule:{rule_id}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached Sigma rule {rule_id}")
                return cached_data
            
            # Get from DynamoDB
            logger.info(f"Loading Sigma rule {rule_id} from DynamoDB")
            response = self.sigma_rules_metadata_table.get_item(Key={'rule_id': rule_id})
            
            if 'Item' not in response:
                logger.warning(f"Sigma rule {rule_id} not found")
                return None
            
            rule = response['Item']
            
            # Cache result
            self.cache.set(cache_key, rule, ttl=self.cache_ttl)
            
            return rule
            
        except Exception as e:
            logger.exception(f"Error getting Sigma rule {rule_id}")
            return None
    
    async def get_sigma_rule_content(self, rule_id: str) -> Optional[Dict]:
        """
        Get full Sigma rule content from S3 (includes YAML content).
        
        Args:
            rule_id: Sigma rule identifier
            
        Returns:
            Full rule dict with content, or None if not found
        """
        try:
            # First get metadata
            metadata = await self.get_sigma_rule(rule_id)
            if not metadata:
                return None
            
            # Get S3 references
            s3_bucket = metadata.get('s3_bucket')
            s3_key = metadata.get('s3_key')
            
            if not s3_bucket or not s3_key:
                logger.warning(f"Sigma rule {rule_id} missing S3 reference")
                return metadata  # Return metadata only
            
            # Download full content from S3
            logger.info(f"Loading Sigma rule content from S3: {s3_key}")
            rule_obj = self.s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            rule_content = rule_obj['Body'].read().decode('utf-8')
            
            # Parse YAML
            rule_data = yaml.safe_load(rule_content)
            
            # Merge metadata with content
            rule_data['metadata'] = metadata
            
            return rule_data
            
        except Exception as e:
            logger.exception(f"Error getting Sigma rule content for {rule_id}")
            return None
    
    async def update_rule_status(self, rule_id: str, new_status: str) -> bool:
        """
        Update Sigma rule status (enable/disable).

        Args:
            rule_id: Rule identifier
            new_status: New status ('stable' or 'deprecated')

        Returns:
            True if successful
        """
        try:
            self.sigma_rules_metadata_table.update_item(
                Key={'rule_id': rule_id},
                UpdateExpression="SET #status = :status",
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': new_status}
            )
            # Bust cached reads so the change is visible immediately, not after
            # the 300s TTL. Drop the per-rule entry AND every list entry (the
            # list cache key encodes status/level/limit/cursor, so invalidate the
            # whole `sigma_rules:` family by prefix rather than guessing keys).
            self.cache.invalidate(f"sigma_rule:{rule_id}")
            self.cache.invalidate_prefix("sigma_rules:")
            # WS24 M3.2: a status change alters the `stable` (enforced) set. Bump
            # the shared version row so OTHER tasks reload their enforcement cache
            # within version_check_interval, and write-through-invalidate THIS
            # task's enforcement cache so the change is effective immediately.
            self._bump_enforcement_version()
            logger.info(f"Updated rule {rule_id} status to {new_status}")
            return True
        except Exception as e:
            logger.error(f"Error updating rule status: {e}")
            return False

    def _bump_enforcement_version(self) -> None:
        """Increment the shared sigma rule-set version + drop the local
        enforcement cache (WS24 M3.2). Best-effort: a coordination failure must
        NOT fail the CRUD write — it just falls back to TTL-bounded propagation."""
        try:
            from app.validators.sigma_engine import (
                _SIGMA_VERSION_ITEM_ID,
                get_sigma_engine,
            )
            self.sigma_rules_metadata_table.update_item(
                Key={'rule_id': _SIGMA_VERSION_ITEM_ID},
                UpdateExpression="ADD #v :one",
                ExpressionAttributeNames={'#v': 'version'},  # 'version' is a DDB reserved word
                ExpressionAttributeValues={':one': 1},
            )
            get_sigma_engine().invalidate()
        except Exception as e:
            logger.warning(f"sigma enforcement version bump failed (TTL fallback): {e}")

    async def update_rule_match_count(
        self,
        rule_id: str,
        increment: int = 1
    ) -> bool:
        """
        Update match count for a Sigma rule (atomic increment).

        DEAD CODE — DO NOT WIRE THIS UP. Match counts now live in CloudWatch
        (the SigmaRuleMatches metric, per RuleId, emitted by SigmaEngine on each
        match) and are read back via MetricsQueryService.sigma_match_counts().
        The console reads CloudWatch, never the DDB ``stats.match_count_*``
        fields this method writes. Kept only so the existing unit tests and the
        DDB schema stay intact; nothing in the request path calls it.

        Args:
            rule_id: Sigma rule identifier
            increment: Amount to increment (default: 1)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Atomic increment using UpdateExpression
            self.sigma_rules_metadata_table.update_item(
                Key={'rule_id': rule_id},
                UpdateExpression="""
                    SET stats.match_count_24h = if_not_exists(stats.match_count_24h, :zero) + :inc,
                        stats.match_count_7d = if_not_exists(stats.match_count_7d, :zero) + :inc,
                        stats.last_matched = :timestamp
                """,
                ExpressionAttributeValues={
                    ':zero': 0,
                    ':inc': increment,
                    ':timestamp': DDBDecimal(str(int(time.time())))
                }
            )
            
            logger.debug(f"Updated match count for Sigma rule {rule_id}")
            
            # Invalidate cache
            self.cache.invalidate(f"sigma_rule:{rule_id}")
            
            return True
            
        except Exception as e:
            logger.warning(f"Error updating match count for {rule_id}: {e}")
            return False
    
    def _publish_metrics(self, operation: str, latency_ms: float, cache_hit: bool):
        """
        Publish CloudWatch metrics for Sigma Rules Service operations.
        
        Args:
            operation: Operation name (GetSigmaRules, GetSigmaRule)
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
