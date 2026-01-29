"""
Metrics Service - Query Summary Metrics

Provides functionality to query summary metrics from CloudWatch Logs.
"""
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class MetricsService:
    """
    Query summary metrics from CloudWatch Logs.
    
    Uses CloudWatch Logs Insights to aggregate metrics.
    """
    
    def __init__(self):
        self.cloudwatch_logs = boto3.client('logs', region_name=settings.aws_region)
        self.log_group = settings.cloudwatch_log_group
    
    async def query_metrics(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query summary metrics for time range.
        
        Args:
            since: Start time (ISO 8601 timestamp)
            until: End time (ISO 8601 timestamp)
            
        Returns:
            Dict with aggregated metrics
        """
        try:
            # Parse time range
            start_time, end_time = self._parse_time_range(since, until)
            
            # Query metrics from CloudWatch Logs
            metrics = await self._query_aggregated_metrics(start_time, end_time)
            
            return {
                "time_range": {
                    "since": datetime.utcfromtimestamp(start_time / 1000).isoformat() + "Z",
                    "until": datetime.utcfromtimestamp(end_time / 1000).isoformat() + "Z"
                },
                "requests": metrics.get("requests", {}),
                "latency": metrics.get("latency", {}),
                "sessions": metrics.get("sessions", {}),
                "threats": metrics.get("threats", {})
            }
            
        except Exception as e:
            logger.exception(f"Failed to query metrics: {e}")
            raise
    
    def _parse_time_range(
        self,
        since: Optional[str],
        until: Optional[str]
    ) -> tuple[int, int]:
        """
        Parse time range to Unix timestamps (milliseconds).
        
        Returns:
            (start_time_ms, end_time_ms)
        """
        # Default: last 1 hour
        if not until:
            end_time = datetime.now(timezone.utc)
        else:
            end_time = datetime.fromisoformat(until.replace('Z', '+00:00'))
        
        if not since:
            start_time = end_time - timedelta(hours=1)
        else:
            start_time = datetime.fromisoformat(since.replace('Z', '+00:00'))
        
        # Convert to milliseconds
        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)
        
        return start_time_ms, end_time_ms
    
    async def _query_aggregated_metrics(
        self,
        start_time_ms: int,
        end_time_ms: int
    ) -> Dict[str, Any]:
        """
        Query aggregated metrics using CloudWatch Insights.

        Args:
            start_time_ms: Start time in milliseconds
            end_time_ms: End time in milliseconds

        Returns:
            Dict with aggregated metrics
        """
        # For MVP, return simple aggregated metrics
        # In production, this would use multiple CloudWatch Insights queries

        try:
            # Query 1: Basic request/latency metrics
            basic_metrics = await self._query_basic_metrics(start_time_ms, end_time_ms)

            # Query 2: Threat type breakdown
            threat_metrics = await self._query_threat_breakdown(start_time_ms, end_time_ms)

            # Merge results
            basic_metrics['threats'] = threat_metrics

            return basic_metrics

        except ClientError as e:
            logger.exception(f"CloudWatch metrics query error: {e}")
            return self._default_metrics()

    async def _query_basic_metrics(
        self,
        start_time_ms: int,
        end_time_ms: int
    ) -> Dict[str, Any]:
        """Query basic request and latency metrics."""
        try:
            # Query for basic counts
            query = """
            fields @timestamp, @message
            | parse @message /(?<log_data>.*)/
            | stats count() as total_requests,
                    sum(decision = "ALLOW") as allow_count,
                    sum(decision = "DENY") as deny_count,
                    avg(latency_ms) as avg_latency,
                    pct(latency_ms, 50) as p50_latency,
                    pct(latency_ms, 95) as p95_latency,
                    pct(latency_ms, 99) as p99_latency
            """

            # Start query
            response = self.cloudwatch_logs.start_query(
                logGroupName=self.log_group,
                startTime=start_time_ms,
                endTime=end_time_ms,
                queryString=query
            )

            query_id = response['queryId']

            # Wait for results (simplified for MVP)
            import time
            max_wait = 5
            start = time.time()

            while time.time() - start < max_wait:
                result = self.cloudwatch_logs.get_query_results(queryId=query_id)

                if result['status'] == 'Complete':
                    return self._parse_metrics_results(result['results'])

                elif result['status'] == 'Failed':
                    logger.error("Basic metrics query failed")
                    return self._default_metrics()

                time.sleep(0.5)

            # Timeout
            logger.warning("Basic metrics query timeout")
            return self._default_metrics()

        except ClientError as e:
            logger.exception(f"Basic metrics query error: {e}")
            return self._default_metrics()

    async def _query_threat_breakdown(
        self,
        start_time_ms: int,
        end_time_ms: int
    ) -> Dict[str, int]:
        """Query threat type breakdown from denied requests."""
        try:
            # Query for threat types - CloudWatch auto-parses JSON
            query = """
            fields @timestamp, decision, threat_type, violation_type
            | filter decision = "DENY"
            | filter ispresent(threat_type) or ispresent(violation_type)
            | stats count() by coalesce(threat_type, violation_type, "UNKNOWN") as threat
            """

            # Start query
            response = self.cloudwatch_logs.start_query(
                logGroupName=self.log_group,
                startTime=start_time_ms,
                endTime=end_time_ms,
                queryString=query
            )

            query_id = response['queryId']

            # Wait for results
            import time
            max_wait = 5
            start = time.time()

            while time.time() - start < max_wait:
                result = self.cloudwatch_logs.get_query_results(queryId=query_id)

                if result['status'] == 'Complete':
                    return self._parse_threat_results(result['results'])

                elif result['status'] == 'Failed':
                    logger.error("Threat breakdown query failed")
                    return {}

                time.sleep(0.5)

            # Timeout
            logger.warning("Threat breakdown query timeout")
            return {}

        except ClientError as e:
            logger.exception(f"Threat breakdown query error: {e}")
            return {}

    def _parse_threat_results(self, results: list) -> Dict[str, int]:
        """
        Parse threat breakdown results.

        Args:
            results: Raw query results

        Returns:
            Dict mapping threat type to count (e.g., {"PROMPT_INJECTION": 12, "POLICY_VIOLATION": 8})
        """
        if not results:
            return {}

        threat_counts = {}

        for result_row in results:
            values = {field['field']: field['value'] for field in result_row}
            threat_type = values.get('threat', 'UNKNOWN')
            count = int(values.get('count()', 0))

            if threat_type and count > 0:
                threat_counts[threat_type] = count

        return threat_counts
    
    def _parse_metrics_results(self, results: list) -> Dict[str, Any]:
        """
        Parse CloudWatch Insights metrics results.
        
        Args:
            results: Raw query results
            
        Returns:
            Parsed metrics dict
        """
        if not results or not results[0]:
            return self._default_metrics()
        
        # Extract values from first result row
        result_row = results[0]
        values = {field['field']: field['value'] for field in result_row}
        
        total_requests = int(values.get('total_requests', 0))
        allow_count = int(values.get('allow_count', 0))
        deny_count = int(values.get('deny_count', 0))
        
        deny_rate = deny_count / total_requests if total_requests > 0 else 0.0
        
        return {
            "requests": {
                "total": total_requests,
                "allow_count": allow_count,
                "deny_count": deny_count,
                "deny_rate": round(deny_rate, 3)
            },
            "latency": {
                "avg_ms": round(float(values.get('avg_latency', 0)), 2),
                "p50_ms": round(float(values.get('p50_latency', 0)), 2),
                "p95_ms": round(float(values.get('p95_latency', 0)), 2),
                "p99_ms": round(float(values.get('p99_latency', 0)), 2)
            },
            "sessions": {
                "active": 0,  # Would need separate query
                "quarantined": 0,
                "suspended": 0
            },
            "threats": {}  # Populated by _query_threat_breakdown()
        }
    
    def _default_metrics(self) -> Dict[str, Any]:
        """Return default empty metrics"""
        return {
            "requests": {
                "total": 0,
                "allow_count": 0,
                "deny_count": 0,
                "deny_rate": 0.0
            },
            "latency": {
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0
            },
            "sessions": {
                "active": 0,
                "quarantined": 0,
                "suspended": 0
            },
            "threats": {}
        }
