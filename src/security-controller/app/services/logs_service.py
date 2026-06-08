"""
Logs Service - Query Audit Logs from CloudWatch

Provides functionality to query audit logs from CloudWatch Logs using CloudWatch Insights.
"""
import logging
import json
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class LogsService:
    """
    Query audit logs from CloudWatch Logs.
    
    Uses CloudWatch Logs Insights for flexible querying.
    """
    
    def __init__(self):
        self.cloudwatch_logs = boto3.client('logs', region_name=settings.aws_region)
        self.log_group = settings.cloudwatch_log_group
    
    async def query_logs(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        decision: Optional[str] = None,
        threat_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query audit logs with filters.
        
        Args:
            since: Start time (ISO 8601 timestamp)
            until: End time (ISO 8601 timestamp)
            limit: Max results (default 100, max 1000)
            session_id: Filter by session ID
            agent_id: Filter by agent ID
            decision: Filter by decision (ALLOW/DENY)
            threat_type: Filter by threat type
            
        Returns:
            Dict with logs, total, next_token (canonical pagination, LLD 21 §11.1)
        """
        try:
            # Parse time range
            start_time, end_time = self._parse_time_range(since, until)
            
            # Build CloudWatch Insights query
            query = self._build_query(
                session_id=session_id,
                agent_id=agent_id,
                decision=decision,
                threat_type=threat_type,
                limit=min(limit, 1000)  # Cap at 1000
            )
            
            # Execute query
            logs = await self._execute_query(query, start_time, end_time)
            
            # Canonical pagination (LLD 21 §11.1): next_token only (null = last
            # page). CloudWatch Logs Insights paging is not wired in MVP, so the
            # token is always null here.
            return {
                "logs": logs,
                "total": len(logs),
                "next_token": None
            }
            
        except Exception as e:
            logger.exception(f"Failed to query logs: {e}")
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
    
    def _build_query(
        self,
        session_id: Optional[str],
        agent_id: Optional[str],
        decision: Optional[str],
        threat_type: Optional[str],
        limit: int
    ) -> str:
        """
        Build CloudWatch Insights query string.
        
        Returns:
            Query string
        """
        # Base query - select all fields
        query_parts = [
            "fields @timestamp, @message",
            "| parse @message /(?<log_data>.*)/"
        ]
        
        # Add filters
        filters = []
        if session_id:
            filters.append(f'@message like "{session_id}"')
        if agent_id:
            filters.append(f'@message like "{agent_id}"')
        if decision:
            filters.append(f'@message like "\\"decision\\": \\"{decision}\\""')
        if threat_type:
            filters.append(f'@message like "{threat_type}"')
        
        if filters:
            query_parts.append("| filter " + " and ".join(filters))
        
        # Sort and limit
        query_parts.append("| sort @timestamp desc")
        query_parts.append(f"| limit {limit}")
        
        return " ".join(query_parts)
    
    async def _execute_query(
        self,
        query: str,
        start_time_ms: int,
        end_time_ms: int
    ) -> List[Dict[str, Any]]:
        """
        Execute CloudWatch Insights query and wait for results.
        
        Args:
            query: CloudWatch Insights query string
            start_time_ms: Start time in milliseconds
            end_time_ms: End time in milliseconds
            
        Returns:
            List of log entries
        """
        try:
            # Start query
            response = self.cloudwatch_logs.start_query(
                logGroupName=self.log_group,
                startTime=start_time_ms,
                endTime=end_time_ms,
                queryString=query
            )
            
            query_id = response['queryId']
            logger.debug(f"Started CloudWatch Insights query: {query_id}")
            
            # Poll for results (max 15 seconds for large time ranges)
            max_wait = 15
            start = time.time()
            
            while time.time() - start < max_wait:
                result = self.cloudwatch_logs.get_query_results(queryId=query_id)
                status = result['status']
                
                if status == 'Complete':
                    # Parse results
                    logs = self._parse_query_results(result['results'])
                    logger.debug(f"Query complete: {len(logs)} logs found")
                    return logs
                
                elif status == 'Failed':
                    logger.error(f"Query failed: {result.get('statistics', {})}")
                    return []
                
                # Wait before polling again
                time.sleep(0.5)
            
            # Timeout
            logger.warning(f"Query timeout after {max_wait}s")
            return []
            
        except ClientError as e:
            logger.exception(f"CloudWatch query error: {e}")
            return []
    
    def _parse_query_results(self, results: List[List[Dict]]) -> List[Dict[str, Any]]:
        """
        Parse CloudWatch Insights query results.
        
        Args:
            results: Raw query results from CloudWatch
            
        Returns:
            List of parsed log entries
        """
        logs = []
        
        for result in results:
            try:
                # Find @message field
                message_field = next(
                    (field for field in result if field['field'] == '@message'),
                    None
                )
                
                if message_field:
                    # Parse JSON message
                    log_data = json.loads(message_field['value'])
                    logs.append(log_data)
                    
            except (json.JSONDecodeError, StopIteration, KeyError) as e:
                logger.warning(f"Failed to parse log entry: {e}")
                continue
        
        return logs
