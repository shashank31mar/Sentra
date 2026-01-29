"""
CloudWatch Logs Client
Sentra MVP - Workstream 13, Task 2.2
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import boto3

logger = logging.getLogger(__name__)

AUDIT_LOG_GROUP = os.environ.get("AUDIT_LOG_GROUP", "/sentra/audit-logs")


class CloudWatchLogsClient:
    """Client for writing demo scenario logs to CloudWatch"""
    
    def __init__(self, region: str = None):
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.logs_client = boto3.client('logs', region_name=self.region)
        self.log_group = AUDIT_LOG_GROUP
    
    async def put_log_event(
        self,
        log_stream: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        Write log event to CloudWatch Logs
        
        Args:
            log_stream: Log stream name (e.g., "demo/run-abc123")
            message: Log message dict (will be JSON serialized)
        
        Returns:
            True if successful
        """
        try:
            # Ensure log stream exists
            self._ensure_log_stream(log_stream)
            
            # Add timestamp if not present
            if "timestamp" not in message:
                message["timestamp"] = datetime.utcnow().isoformat()
            
            # Put log event
            self.logs_client.put_log_events(
                logGroupName=self.log_group,
                logStreamName=log_stream,
                logEvents=[{
                    'timestamp': int(datetime.utcnow().timestamp() * 1000),
                    'message': json.dumps(message)
                }]
            )
            
            logger.debug(f"Logged event to {self.log_group}/{log_stream}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write CloudWatch log: {e}")
            return False
    
    def _ensure_log_stream(self, log_stream: str):
        """Create log stream if it doesn't exist"""
        try:
            self.logs_client.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=log_stream
            )
        except self.logs_client.exceptions.ResourceAlreadyExistsException:
            pass  # Stream already exists
        except Exception as e:
            logger.warning(f"Could not create log stream {log_stream}: {e}")

    async def query_demo_logs(
        self,
        scenario_id: Optional[str] = None,
        hours: int = 24,
        agent_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query demo logs from CloudWatch using Logs Insights

        Args:
            scenario_id: Filter by scenario ID (optional)
            hours: Time range in hours (default 24)
            agent_type: Filter by agent type (optional)

        Returns:
            List of log entries matching filters
        """
        try:
            # Build query
            fields = ["@timestamp", "@message"]
            query_parts = ["fields @timestamp, @message"]

            # Filter by agent_type if specified
            if agent_type:
                query_parts.append(f"| filter agent_type = '{agent_type}'")

            # Filter by scenario_id if specified
            if scenario_id:
                query_parts.append(f"| filter scenario_id = '{scenario_id}'")

            query_parts.append("| sort @timestamp desc")
            query_parts.append(f"| limit 1000")

            query_string = "\n".join(query_parts)

            # Calculate time range
            end_time = int(datetime.now(timezone.utc).timestamp())
            start_time = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

            # Start query
            response = self.logs_client.start_query(
                logGroupName=self.log_group,
                startTime=start_time,
                endTime=end_time,
                queryString=query_string
            )

            query_id = response['queryId']

            # Poll for results (max 15 seconds, check every 0.5s)
            import asyncio
            for _ in range(30):
                await asyncio.sleep(0.5)
                result = self.logs_client.get_query_results(queryId=query_id)

                status = result['status']
                if status == 'Complete':
                    # Parse results
                    logs = []
                    for row in result.get('results', []):
                        # Convert CloudWatch Insights result format to dict
                        log_entry = {}
                        message_str = None

                        for field in row:
                            if field['field'] == '@message':
                                message_str = field['value']

                        if message_str:
                            try:
                                # Parse JSON message
                                log_entry = json.loads(message_str)
                                logs.append(log_entry)
                            except json.JSONDecodeError:
                                logger.warning(f"Could not parse log message: {message_str[:100]}")

                    logger.info(f"Retrieved {len(logs)} logs from CloudWatch (agent_type={agent_type}, scenario={scenario_id})")
                    return logs

                elif status == 'Failed' or status == 'Cancelled':
                    logger.error(f"CloudWatch query failed: {status}")
                    return []

            logger.warning("CloudWatch query timed out")
            return []

        except Exception as e:
            logger.error(f"Error querying CloudWatch logs: {e}")
            return []
