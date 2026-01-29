"""
Audit Logger for Security Controller

Writes validation decisions to CloudWatch Logs for audit trail.
All logging is asynchronous (fire-and-forget) to avoid blocking validation.
"""
import logging
import json
import time
from typing import Dict, Optional, Any
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Writes audit logs to CloudWatch Logs.
    
    Log Structure:
    - Log Group: /sentra/audit-logs
    - Log Stream: One per session_id
    - Format: JSON for CloudWatch Insights queries
    """
    
    def __init__(self):
        self.cloudwatch_logs = boto3.client('logs', region_name=settings.aws_region)
        self.log_group = settings.cloudwatch_log_group
        self._ensure_log_group_exists()
    
    def _ensure_log_group_exists(self):
        """Create log group if it doesn't exist"""
        try:
            self.cloudwatch_logs.create_log_group(logGroupName=self.log_group)
            logger.info(f"Created CloudWatch log group: {self.log_group}")
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                logger.warning(f"Could not create log group: {e}")
    
    async def log_decision(
        self,
        decision: str,
        request: Dict[str, Any],
        session: Dict[str, Any],
        validation_result: Optional[Dict[str, Any]] = None,
        latency_ms: float = 0.0
    ):
        """
        Log validation decision to CloudWatch Logs.
        
        Args:
            decision: ALLOW or DENY
            request: ValidationRequest dict
            session: Session context dict
            validation_result: Result from validator (for DENY)
            latency_ms: Validation latency in milliseconds
        
        Note: This is fire-and-forget. Logging failures don't block validation.
        """
        try:
            # Build log event
            log_event = self._build_log_event(
                decision=decision,
                request=request,
                session=session,
                validation_result=validation_result,
                latency_ms=latency_ms
            )
            
            # Write to CloudWatch Logs
            await self._write_log_event(
                session_id=request.get("session_id"),
                log_event=log_event
            )
            
        except Exception as e:
            # Log error but don't raise - logging failures should not block validation
            logger.exception(f"Failed to write audit log: {e}")
    
    def _build_log_event(
        self,
        decision: str,
        request: Dict[str, Any],
        session: Dict[str, Any],
        validation_result: Optional[Dict[str, Any]],
        latency_ms: float
    ) -> Dict[str, Any]:
        """Build audit log event structure"""
        
        # Base event
        event = {
            "request_id": request.get("request_id"),
            "session_id": request.get("session_id"),
            "agent_id": request.get("agent_id"),
            "tool_name": request.get("tool_name"),
            "operation_type": request.get("operation_type"),
            "decision": decision,
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "latency_ms": round(latency_ms, 2)
        }
        
        # Add trust score info
        trust_score_before = session.get("trust_score", 100.0)
        event["trust_score_before"] = trust_score_before
        
        if decision == "DENY" and validation_result:
            # DENY-specific fields
            event["reason"] = validation_result.get("reason", "Unknown")
            
            # Only include optional fields if they have values (not None)
            threat_type = validation_result.get("threat_type")
            if threat_type:
                event["threat_type"] = threat_type
            
            severity = validation_result.get("severity")
            if severity:
                event["severity"] = severity
            
            matched_rule = validation_result.get("matched_rule")
            if matched_rule:
                event["matched_rule"] = matched_rule
            
            violation_type = validation_result.get("violation_type")
            if violation_type:
                event["violation_type"] = violation_type
            
            # Calculate trust score after penalty
            penalty = validation_result.get("penalty", 0)
            trust_score_after = max(0.0, trust_score_before + penalty)
            event["trust_score_after"] = trust_score_after
            event["trust_delta"] = penalty
        else:
            # ALLOW-specific fields
            event["reason"] = "All validation checks passed"
            event["trust_score_after"] = trust_score_before
            event["trust_delta"] = 0.0
        
        # Add action_id for reversible actions
        if request.get("operation_type") == "WRITE" and request.get("tool_name") in ["process_refund"]:
            # Generate action_id for reversible actions
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            import secrets
            random_hex = secrets.token_hex(3)
            action_id = f"act-{request.get('tool_name')}-{timestamp_str}-{random_hex}"
            event["action_id"] = action_id
            event["reversible"] = True
            event["rollback_status"] = "NOT_ROLLED_BACK"
        
        # Add user input (truncated for security)
        user_input = request.get("user_input", "")
        event["user_input"] = user_input[:200] if len(user_input) > 200 else user_input
        
        # Add multi-agent context (Workstream 12)
        context = request.get("context", {})
        multi_agent_context = {
            "conversation_id": context.get("conversation_id"),
            "parent_request_id": context.get("parent_request_id"),
            "caller_agent_id": context.get("caller_agent_id"),
            "call_depth": context.get("call_depth", 0)
        }
        event["multi_agent_context"] = multi_agent_context
        
        # Add tool_params for rollback support
        event["tool_params"] = request.get("tool_params", {})
        
        return event
    
    async def _write_log_event(self, session_id: str, log_event: Dict[str, Any]):
        """
        Write log event to CloudWatch Logs.
        
        Uses session_id as log stream name for easy querying.
        """
        try:
            log_stream_name = session_id
            
            # Create log stream if it doesn't exist
            try:
                self.cloudwatch_logs.create_log_stream(
                    logGroupName=self.log_group,
                    logStreamName=log_stream_name
                )
            except ClientError as e:
                if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                    raise
            
            # Put log event
            self.cloudwatch_logs.put_log_events(
                logGroupName=self.log_group,
                logStreamName=log_stream_name,
                logEvents=[
                    {
                        'timestamp': int(time.time() * 1000),
                        'message': json.dumps(log_event)
                    }
                ]
            )
            
            logger.debug(f"Wrote audit log for session {session_id}")
            
        except Exception as e:
            logger.exception(f"Failed to write log event to CloudWatch: {e}")
            # Don't raise - logging failures should not block validation

    async def query_logs_by_conversation(
        self,
        conversation_id: str,
        start_time_hours_ago: int = 24
    ) -> list:
        """
        Query all audit logs for a conversation using CloudWatch Logs Insights.
        
        Args:
            conversation_id: Conversation identifier
            start_time_hours_ago: How far back to search (default 24 hours)
            
        Returns:
            List of log entries sorted by timestamp
        """
        try:
            # Build CloudWatch Logs Insights query
            query = f"""
            fields @timestamp, @message
            | filter multi_agent_context.conversation_id = "{conversation_id}"
            | sort @timestamp asc
            | limit 1000
            """
            
            # Calculate time range
            end_time = int(time.time())
            start_time = end_time - (start_time_hours_ago * 3600)
            
            # Start query
            response = self.cloudwatch_logs.start_query(
                logGroupName=self.log_group,
                queryString=query,
                startTime=start_time,
                endTime=end_time
            )
            
            query_id = response['queryId']
            
            # Wait for query to complete (with timeout)
            max_attempts = 30
            for attempt in range(max_attempts):
                result = self.cloudwatch_logs.get_query_results(queryId=query_id)
                status = result['status']
                
                if status == 'Complete':
                    break
                elif status in ['Failed', 'Cancelled']:
                    logger.error(f"CloudWatch Logs query {status}: {query_id}")
                    return []
                
                time.sleep(0.5)
            else:
                logger.error(f"CloudWatch Logs query timed out: {query_id}")
                return []
            
            # Parse results
            logs = []
            for row in result.get('results', []):
                message_field = next(
                    (f for f in row if f['field'] == '@message'),
                    None
                )
                if message_field:
                    try:
                        log_entry = json.loads(message_field['value'])
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse log entry: {message_field['value'][:100]}")
            
            logger.info(
                f"Found {len(logs)} logs for conversation {conversation_id}",
                extra={"conversation_id": conversation_id, "count": len(logs)}
            )
            return logs
            
        except ClientError as e:
            logger.exception(f"CloudWatch Logs query failed: {e}")
            return []
        except Exception as e:
            logger.exception(f"Unexpected error querying logs: {e}")
            return []
