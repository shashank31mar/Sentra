"""
Session Manager - DynamoDB CRUD with Atomic Updates

Handles all session state operations with atomic trust score updates
to prevent race conditions.

MVP: Uses atomic increment/decrement (UpdateExpression)
Phase 2: Will migrate to optimistic locking with version field
"""
import time
import logging
from typing import Dict, Optional, List, Any
from decimal import Decimal
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)

# Constants
AWS_SERVICE_DYNAMODB = 'dynamodb'


class SessionNotFoundError(Exception):
    """Raised when session doesn't exist"""
    pass


class SessionUpdateError(Exception):
    """Raised when session update fails"""
    pass


class SessionManager:
    """
    Manages session state in DynamoDB with atomic updates.
    
    Key Features:
    - Atomic trust score updates (no race conditions)
    - Asymmetric recovery (harder to recover at lower scores)
    - Tool history management (last 10 tools only)
    - Quarantine status management
    """
    
    def __init__(self):
        self.dynamodb = boto3.resource(AWS_SERVICE_DYNAMODB, region_name=settings.aws_region)
        self.table = self.dynamodb.Table(settings.dynamodb_session_table)
        
        # Trust scoring thresholds
        self.INITIAL_SCORE = settings.trust_initial_score
        self.QUARANTINE_THRESHOLD = settings.trust_quarantine_threshold
        self.SUSPEND_THRESHOLD = settings.trust_suspend_threshold
        
        # Penalties for violations
        self.PENALTIES = {
            "PROMPT_INJECTION": -20,
            "JAILBREAK": -30,
            "DATA_EXFILTRATION": -25,
            "POLICY_VIOLATION": -15,
            "RATE_LIMIT_EXCEEDED": -10,
            "SEQUENCE_VIOLATION": -15,
            "UNAUTHORIZED_TOOL": -15,
            "UNAUTHORIZED_AGENT_INVOCATION": -15,
            "SYSTEM_ERROR": -10
        }
    
    async def get_session(self, session_id: str) -> Optional[Dict]:
        """
        Get existing session without creating if not found.
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            Session dictionary or None if not found
        """
        try:
            response = self.table.get_item(Key={'session_id': session_id})
            
            if 'Item' in response:
                session = self._deserialize_session(response['Item'])
                logger.debug(f"Retrieved session: {session_id}")
                return session
            
            return None
            
        except ClientError as e:
            logger.exception(f"DynamoDB error getting session {session_id}")
            return None
    
    async def get_or_create_session(
        self,
        session_id: str,
        user_id: str = "unknown",
        agent_id: str = "unknown"
    ) -> Dict:
        """
        Get existing session or create new one with initial trust score.
        
        Args:
            session_id: Unique session identifier
            user_id: User identifier (optional)
            agent_id: Agent identifier (optional)
            
        Returns:
            Session dictionary with all fields
        """
        try:
            # Try to get existing session
            response = self.table.get_item(Key={'session_id': session_id})
            
            if 'Item' in response:
                session = self._deserialize_session(response['Item'])
                logger.info(f"Retrieved existing session: {session_id}")
                return session
            
            # Create new session
            current_time = int(time.time() * 1000)  # milliseconds
            ttl = int(time.time()) + (24 * 60 * 60)  # 24 hours from now
            
            new_session = {
                'session_id': session_id,
                'user_id': user_id,
                'agent_id': agent_id,
                'created_at': current_time,
                'last_activity': current_time,
                'version': 1,
                
                # Counters
                'total_requests': 0,
                'allow_count': 0,
                'deny_count': 0,
                
                # Trust scoring
                'trust_score': Decimal(str(self.INITIAL_SCORE)),
                'quarantine_status': 'active',
                'consecutive_allows': 0,
                
                # Tool history (last 10 only)
                'tool_history': [],
                
                # Abuse counters
                'abuse_counters': {
                    'calls_this_minute': 0,
                    'last_minute_reset': int(time.time()) // 60
                },
                
                'ttl': ttl
            }
            
            self.table.put_item(Item=new_session)
            logger.info(f"Created new session: {session_id} with trust_score={self.INITIAL_SCORE}")
            
            return self._deserialize_session(new_session)
            
        except ClientError as e:
            logger.exception(f"DynamoDB error getting/creating session {session_id}")
            raise SessionUpdateError(f"Failed to get/create session: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error getting/creating session {session_id}")
            raise SessionUpdateError(f"Unexpected error: {e}")
    
    async def update_trust_score_deny(
        self,
        session_id: str,
        violation_type: str,
        reason: str = ""
    ) -> Dict:
        """
        Update trust score after DENY decision (atomic decrement).
        
        Args:
            session_id: Session to update
            violation_type: Type of violation (determines penalty)
            reason: Human-readable reason for denial
            
        Returns:
            Updated session dictionary
        """
        try:
            penalty = self.PENALTIES.get(violation_type, -10)
            current_time = int(time.time() * 1000)
            
            # Atomic update with UpdateExpression
            response = self.table.update_item(
                Key={'session_id': session_id},
                UpdateExpression="""
                    SET trust_score = if_not_exists(trust_score, :initial) + :penalty,
                        consecutive_allows = :zero,
                        deny_count = if_not_exists(deny_count, :zero) + :one,
                        total_requests = if_not_exists(total_requests, :zero) + :one,
                        last_activity = :timestamp,
                        quarantine_status = :new_status
                """,
                ExpressionAttributeValues={
                    ':penalty': Decimal(str(penalty)),
                    ':zero': 0,
                    ':one': 1,
                    ':timestamp': current_time,
                    ':initial': Decimal(str(self.INITIAL_SCORE)),
                    ':new_status': 'pending'  # Will be updated below
                },
                ReturnValues='ALL_NEW'
            )
            
            updated_session = self._deserialize_session(response['Attributes'])
            
            # Update quarantine status based on new trust score
            new_status = self._get_quarantine_status(updated_session['trust_score'])
            
            # Second update to set correct quarantine status
            response = self.table.update_item(
                Key={'session_id': session_id},
                UpdateExpression="SET quarantine_status = :status",
                ExpressionAttributeValues={':status': new_status},
                ReturnValues='ALL_NEW'
            )
            
            updated_session = self._deserialize_session(response['Attributes'])
            
            logger.info(
                f"Session {session_id} DENY: trust_score {updated_session['trust_score']} "
                f"(penalty={penalty}), status={new_status}, reason={reason}"
            )
            
            return updated_session
            
        except ClientError as e:
            logger.exception(f"DynamoDB error updating session {session_id} for DENY")
            raise SessionUpdateError(f"Failed to update session: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error updating session {session_id} for DENY")
            raise SessionUpdateError(f"Unexpected error: {e}")
    
    async def update_trust_score_allow(
        self,
        session_id: str,
        tool_name: str,
        agent_id: Optional[str] = None,
    ) -> Dict:
        """
        Update trust score after ALLOW decision (asymmetric recovery).

        Increments consecutive_allows counter. When threshold reached,
        increments trust_score and resets counter.

        Args:
            session_id: Session to update
            tool_name: Tool that was allowed
            agent_id: Agent that invoked the tool. Recorded in tool_history so
                the context validator can enforce cross_cloud_dependencies
                (Workstream 15). Optional for backward compatibility; entries
                without an agent_id are treated as cross-cloud-unverifiable.

        Returns:
            Updated session dictionary
        """
        try:
            current_time = int(time.time() * 1000)

            # Build the tool_history entry. Workstream 15: include agent_id when
            # provided so cross-cloud dependency rules can identify which agent
            # invoked each prerequisite tool.
            history_entry: Dict[str, Any] = {'tool_name': tool_name, 'timestamp': current_time}
            if agent_id is not None:
                history_entry['agent_id'] = agent_id

            # First, increment consecutive_allows and add to tool_history
            response = self.table.update_item(
                Key={'session_id': session_id},
                UpdateExpression="""
                    SET consecutive_allows = if_not_exists(consecutive_allows, :zero) + :one,
                        allow_count = if_not_exists(allow_count, :zero) + :one,
                        total_requests = if_not_exists(total_requests, :zero) + :one,
                        last_activity = :timestamp,
                        tool_history = list_append(if_not_exists(tool_history, :empty_list), :new_tool)
                """,
                ExpressionAttributeValues={
                    ':zero': 0,
                    ':one': 1,
                    ':timestamp': current_time,
                    ':empty_list': [],
                    ':new_tool': [history_entry]
                },
                ReturnValues='ALL_NEW'
            )
            
            session = self._deserialize_session(response['Attributes'])
            
            # Truncate tool_history to last 10 tools
            if len(session['tool_history']) > 10:
                session['tool_history'] = session['tool_history'][-10:]
                # Convert floats to Decimals for DynamoDB
                history_for_db = [
                    {k: Decimal(str(v)) if isinstance(v, float) else v for k, v in item.items()}
                    for item in session['tool_history']
                ]
                self.table.update_item(
                    Key={'session_id': session_id},
                    UpdateExpression="SET tool_history = :history",
                    ExpressionAttributeValues={':history': history_for_db}
                )
            
            # Check if we should increment trust score
            trust_score = session['trust_score']
            consecutive_allows = session['consecutive_allows']
            
            required_allows = self._get_consecutive_allows_required(trust_score)
            
            if consecutive_allows >= required_allows:
                # Threshold reached - increment trust score
                increment = self._get_increment_amount(trust_score)
                new_score = min(100.0, trust_score + increment)
                
                response = self.table.update_item(
                    Key={'session_id': session_id},
                    UpdateExpression="""
                        SET trust_score = :new_score,
                            consecutive_allows = :zero,
                            quarantine_status = :new_status
                    """,
                    ExpressionAttributeValues={
                        ':new_score': Decimal(str(new_score)),
                        ':zero': 0,
                        ':new_status': self._get_quarantine_status(new_score)
                    },
                    ReturnValues='ALL_NEW'
                )
                
                session = self._deserialize_session(response['Attributes'])
                
                logger.info(
                    f"Session {session_id} ALLOW: trust_score incremented "
                    f"{trust_score:.1f} → {new_score:.1f} "
                    f"(after {consecutive_allows} consecutive allows)"
                )
            else:
                logger.debug(
                    f"Session {session_id} ALLOW: consecutive_allows={consecutive_allows}/{required_allows}"
                )
            
            return session
            
        except ClientError as e:
            logger.exception(f"DynamoDB error updating session {session_id} for ALLOW")
            raise SessionUpdateError(f"Failed to update session: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error updating session {session_id} for ALLOW")
            raise SessionUpdateError(f"Unexpected error: {e}")
    
    async def manual_quarantine(
        self,
        session_id: str,
        reason: str,
        operator_id: str
    ) -> Dict:
        """
        Manually quarantine a session (operator override).
        
        Args:
            session_id: Session to quarantine
            reason: Reason for quarantine
            operator_id: Operator who initiated quarantine
            
        Returns:
            Updated session dictionary
        """
        try:
            current_time = int(time.time() * 1000)
            
            response = self.table.update_item(
                Key={'session_id': session_id},
                UpdateExpression="""
                    SET quarantine_status = :status,
                        quarantine_reason = :reason,
                        quarantine_operator = :operator,
                        quarantine_timestamp = :timestamp,
                        last_activity = :timestamp
                """,
                ExpressionAttributeValues={
                    ':status': 'quarantined',
                    ':reason': reason,
                    ':operator': operator_id,
                    ':timestamp': current_time
                },
                ConditionExpression='attribute_exists(session_id)',
                ReturnValues='ALL_NEW'
            )
            
            session = self._deserialize_session(response['Attributes'])
            
            logger.warning(
                f"Session {session_id} manually quarantined by {operator_id}: {reason}"
            )
            
            return session
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise SessionNotFoundError(f"Session {session_id} not found")
            logger.exception(f"DynamoDB error quarantining session {session_id}")
            raise SessionUpdateError(f"Failed to quarantine session: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error quarantining session {session_id}")
            raise SessionUpdateError(f"Unexpected error: {e}")
    
    def _get_consecutive_allows_required(self, trust_score: float) -> int:
        """
        Number of consecutive successful calls needed for increment.
        HARDER to recover at lower scores (asymmetric recovery).
        """
        if trust_score < 40:
            return 15  # Quarantined: Need 15 consecutive allows
        elif trust_score < 70:
            return 12  # Warning: Need 12 consecutive allows
        else:
            return 10  # Active: Need 10 consecutive allows
    
    def _get_increment_amount(self, trust_score: float) -> float:
        """
        Increment amount when threshold reached.
        SMALLER increments at lower scores (asymmetric recovery).
        """
        if trust_score < 40:
            return 2   # Quarantined: Slow recovery
        elif trust_score < 70:
            return 3   # Warning: Moderate recovery
        else:
            return 5   # Active: Normal recovery
    
    def _get_quarantine_status(self, trust_score: float) -> str:
        """
        Determine quarantine status based on trust score.
        
        Thresholds:
        - 70-100: active (all operations allowed)
        - 40-69: warning (all operations allowed + alerts)
        - 10-39: quarantined (WRITE blocked, READ allowed)
        - 0-9: suspended (all operations blocked)
        """
        if trust_score >= 70:
            return 'active'
        elif trust_score >= 40:
            return 'warning'
        elif trust_score >= 10:
            return 'quarantined'
        else:
            return 'suspended'
    
    def _deserialize_session(self, item: Dict) -> Dict:
        """
        Convert DynamoDB item to Python dict with proper types.
        Converts Decimal to float for JSON serialization.
        """
        session = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                session[key] = float(value)
            elif isinstance(value, dict):
                session[key] = self._deserialize_dict(value)
            elif isinstance(value, list):
                session[key] = [self._deserialize_dict(v) if isinstance(v, dict) else v for v in value]
            else:
                session[key] = value
        return session
    
    def _deserialize_dict(self, d: Dict) -> Dict:
        """Recursively deserialize nested dicts"""
        result = {}
        for key, value in d.items():
            if isinstance(value, Decimal):
                result[key] = float(value)
            elif isinstance(value, dict):
                result[key] = self._deserialize_dict(value)
            else:
                result[key] = value
        return result

    # ============================================================
    # Query Methods (for GET /v1/sessions API)
    # ============================================================
    
    async def query_sessions(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Query sessions with filters for API endpoint.
        
        Args:
            status: Filter by quarantine status (active/quarantined/suspended)
            agent_id: Filter by agent ID
            limit: Max results (default 50, max 200)
            
        Returns:
            Dict with sessions and total count
        """
        try:
            from boto3.dynamodb.conditions import Attr
            
            # Build scan parameters
            scan_kwargs = {
                'Limit': min(limit, 200)  # Cap at 200
            }
            
            # Add filters
            filter_expressions = []
            
            if status:
                filter_expressions.append(Attr('quarantine_status').eq(status))
            
            if agent_id:
                filter_expressions.append(Attr('agent_id').eq(agent_id))
            
            # Combine filters with AND
            if filter_expressions:
                filter_expr = filter_expressions[0]
                for expr in filter_expressions[1:]:
                    filter_expr = filter_expr & expr
                scan_kwargs['FilterExpression'] = filter_expr
            
            # Execute scan
            response = self.table.scan(**scan_kwargs)
            
            # Parse sessions
            sessions = []
            for item in response.get('Items', []):
                sessions.append(self._format_session_for_api(item))
            
            return {
                "sessions": sessions,
                "total": len(sessions)
            }
            
        except ClientError as e:
            logger.exception(f"Failed to query sessions: {e}")
            raise
    
    def _format_session_for_api(self, item: Dict) -> Dict[str, Any]:
        """
        Format DynamoDB item to session info for API response.
        
        Args:
            item: DynamoDB item
            
        Returns:
            Formatted session dict
        """
        return {
            "session_id": item.get('session_id'),
            "user_id": item.get('user_id', 'unknown'),
            "agent_id": item.get('agent_id'),
            "trust_score": float(item.get('trust_score', 100.0)),
            "quarantine_status": item.get('quarantine_status', 'active'),
            "total_requests": int(item.get('total_requests', 0)),
            "allow_count": int(item.get('allow_count', 0)),
            "deny_count": int(item.get('deny_count', 0)),
            "consecutive_allows": int(item.get('consecutive_allows', 0)),
            "created_at": self._format_timestamp(item.get('created_at')),
            "last_activity": self._format_timestamp(item.get('last_activity'))
        }
    
    def _format_timestamp(self, timestamp: Any) -> str:
        """
        Format timestamp to ISO 8601 string.

        Args:
            timestamp: Unix timestamp (seconds or milliseconds) or ISO string

        Returns:
            ISO 8601 formatted string
        """
        if not timestamp:
            return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # If already a string, return as-is
        if isinstance(timestamp, str):
            return timestamp

        # Convert Unix timestamp to ISO 8601
        try:
            # Convert Decimal to float (DynamoDB returns numbers as Decimal)
            timestamp_float = float(timestamp)

            # Handle both seconds and milliseconds
            if timestamp_float > 10000000000:  # Milliseconds
                dt = datetime.fromtimestamp(timestamp_float / 1000, tz=timezone.utc)
            else:  # Seconds
                dt = datetime.fromtimestamp(timestamp_float, tz=timezone.utc)

            return dt.isoformat().replace('+00:00', 'Z')
        except (ValueError, OSError, TypeError):
            return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    # ============================================================
    # Analytics Methods (for Agent Management APIs)
    # ============================================================

    async def get_active_sessions_count(self, agent_id: str) -> int:
        """
        Count active sessions for a specific agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Number of active sessions (excludes expired/suspended)
        """
        try:
            from boto3.dynamodb.conditions import Attr

            response = self.table.scan(
                FilterExpression=Attr('agent_id').eq(agent_id) & Attr('quarantine_status').ne('suspended')
            )

            return len(response.get('Items', []))

        except ClientError as e:
            logger.exception(f"Failed to count active sessions for agent {agent_id}")
            return 0

    async def get_avg_trust_score(self, agent_id: str) -> float:
        """
        Calculate average trust score across all active sessions for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Average trust score (0-100), or 100.0 if no sessions
        """
        try:
            from boto3.dynamodb.conditions import Attr

            response = self.table.scan(
                FilterExpression=Attr('agent_id').eq(agent_id)
            )

            sessions = response.get('Items', [])

            if not sessions:
                return 100.0  # Default if no sessions

            # Calculate average
            total_score = sum(float(s.get('trust_score', 100.0)) for s in sessions)
            return round(total_score / len(sessions), 1)

        except ClientError as e:
            logger.exception(f"Failed to calculate avg trust score for agent {agent_id}")
            return 100.0
