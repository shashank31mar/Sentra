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

logger = logging.getLogger(__name__)


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
    
    async def list_sigma_rules(
        self,
        status: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        List Sigma rules from DynamoDB metadata table with filters.
        
        Data Source: sentra-sigma-rules-metadata table
        Note: Returns metadata only. Full rule content in S3, loaded on-demand.
        
        Args:
            status: Filter by status (stable/experimental/deprecated) (optional)
            level: Filter by severity level (critical/high/medium/low) (optional)
            limit: Max results (default: 50, max: 200)
            
        Returns:
            Dictionary with rules array, total, and has_more flag
        """
        start_time = time.time()
        cache_hit = False
        
        try:
            # Build cache key
            cache_key = f"sigma_rules:status={status}:level={level}:limit={limit}"
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
                    Limit=limit
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
                    Limit=limit
                )
                rules = response.get('Items', [])
                
            else:
                # Scan all rules (no filters)
                logger.info("Scanning all Sigma rules")
                response = self.sigma_rules_metadata_table.scan(Limit=limit)
                rules = response.get('Items', [])
            
            # Apply additional filters if both status and level provided
            if status and level:
                rules = [r for r in rules if r.get('level') == level]
            
            # Sort by match count (most active first)
            # Match counts are stored in metadata (updated by Security Controller)
            rules.sort(
                key=lambda r: r.get('stats', {}).get('match_count_24h', 0),
                reverse=True
            )
            
            result = {
                "rules": rules[:limit],
                "total": len(rules),
                "has_more": len(rules) > limit
            }
            
            # Cache result
            self.cache.set(cache_key, result, ttl=self.cache_ttl)
            
            # Publish metrics
            self._publish_metrics("GetSigmaRules", time.time() - start_time, cache_hit)
            
            return result
            
        except Exception as e:
            logger.exception("Error listing Sigma rules")
            # Return empty array on error (fail-safe for Dashboard)
            return {"rules": [], "total": 0, "has_more": False, "error": str(e)}
    
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
            self.cache.invalidate(f"sigma_rule:{rule_id}")
            logger.info(f"Updated rule {rule_id} status to {new_status}")
            return True
        except Exception as e:
            logger.error(f"Error updating rule status: {e}")
            return False

    async def update_rule_match_count(
        self,
        rule_id: str,
        increment: int = 1
    ) -> bool:
        """
        Update match count for a Sigma rule (atomic increment).
        
        Called by Security Controller when a rule matches.
        
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
