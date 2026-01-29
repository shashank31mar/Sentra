"""
Conversation Service - Query and analyze conversation timelines

Provides conversation-level queries and analytics for multi-agent workflows.
Builds hierarchical timeline from flat audit logs.

Requirements: LLD 12 Section 7.2
Workstream: 12 - Multi-Agent Workflow (Milestone 4)
"""
import logging
import json
from typing import List, Dict, Optional

from app.utils.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

# Structured logging prefix for CloudWatch filtering
LOG_PREFIX = "[WS12-M4-TIMELINE]"


class ConversationService:
    """
    Provides conversation-level queries and analytics.
    
    Features:
    - Query all logs for a conversation_id
    - Build hierarchical timeline showing parent-child relationships
    - Calculate conversation statistics
    """

    def __init__(self):
        self.audit_logger = AuditLogger()

    async def get_timeline(self, conversation_id: str) -> Dict:
        """
        Get complete timeline for a conversation with hierarchical structure.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Dict with timeline tree and statistics
        """
        logger.info(
            f"{LOG_PREFIX} Building timeline for conversation",
            extra={
                "conversation_id": conversation_id,
                "operation": "get_timeline",
                "workstream": "12",
                "milestone": "4"
            }
        )

        # Query CloudWatch Logs for all entries with this conversation_id
        logs = await self.audit_logger.query_logs_by_conversation(conversation_id)
        
        logger.info(
            f"{LOG_PREFIX} Retrieved {len(logs) if logs else 0} audit logs for conversation",
            extra={
                "conversation_id": conversation_id,
                "log_count": len(logs) if logs else 0
            }
        )

        if not logs:
            return {
                "conversation_id": conversation_id,
                "total_requests": 0,
                "timeline": [],
                "statistics": {
                    "total_allowed": 0,
                    "total_denied": 0,
                    "agents_involved": [],
                    "max_call_depth": 0
                }
            }

        # Build hierarchical timeline
        timeline = self._build_timeline_tree(logs)

        # Calculate statistics
        statistics = self._calculate_statistics(logs)

        logger.info(
            f"{LOG_PREFIX} Timeline built successfully",
            extra={
                "conversation_id": conversation_id,
                "total_requests": len(logs),
                "agents_involved": statistics.get("agents_involved", []),
                "max_call_depth": statistics.get("max_call_depth", 0),
                "total_allowed": statistics.get("total_allowed", 0),
                "total_denied": statistics.get("total_denied", 0)
            }
        )

        return {
            "conversation_id": conversation_id,
            "total_requests": len(logs),
            "timeline": timeline,
            "statistics": statistics
        }

    def _build_timeline_tree(self, logs: List[Dict]) -> List[Dict]:
        """
        Build hierarchical tree showing parent-child relationships.

        Args:
            logs: Flat list of audit log entries

        Returns:
            List of root requests with nested children
        """
        # Index logs by request_id
        log_map = {}
        for log in logs:
            request_id = log.get('request_id')
            if request_id:
                # Create a copy to avoid mutating original
                log_copy = log.copy()
                log_copy['children'] = []
                log_map[request_id] = log_copy

        # Find root requests and attach children
        roots = []

        for log in logs:
            request_id = log.get('request_id')
            if not request_id or request_id not in log_map:
                continue

            log_entry = log_map[request_id]
            
            # Get parent_request_id from multi_agent_context
            multi_agent_context = log.get('multi_agent_context', {})
            parent_id = multi_agent_context.get('parent_request_id')

            if not parent_id:
                # Root request (no parent)
                roots.append(log_entry)
            else:
                # Child request - attach to parent
                if parent_id in log_map:
                    log_map[parent_id]['children'].append(log_entry)
                else:
                    # Parent not found in this conversation, treat as root
                    roots.append(log_entry)

        # Sort roots by timestamp
        roots.sort(key=lambda x: x.get('timestamp', ''))

        return roots

    def _calculate_statistics(self, logs: List[Dict]) -> Dict:
        """
        Calculate conversation statistics.

        Args:
            logs: List of audit log entries

        Returns:
            Dict with statistics
        """
        total_allowed = 0
        total_denied = 0
        agents = set()
        max_depth = 0

        for log in logs:
            # Count decisions
            if log.get('decision') == 'ALLOW':
                total_allowed += 1
            elif log.get('decision') == 'DENY':
                total_denied += 1

            # Track agents
            agent_id = log.get('agent_id')
            if agent_id:
                agents.add(agent_id)

            # Track max call depth
            multi_agent_context = log.get('multi_agent_context', {})
            call_depth = multi_agent_context.get('call_depth', 0)
            if call_depth > max_depth:
                max_depth = call_depth

        return {
            "total_allowed": total_allowed,
            "total_denied": total_denied,
            "agents_involved": sorted(list(agents)),
            "max_call_depth": max_depth
        }

    async def get_conversation_summary(self, conversation_id: str) -> Optional[Dict]:
        """
        Get a brief summary of a conversation (without full timeline).

        Args:
            conversation_id: Conversation identifier

        Returns:
            Dict with summary or None if not found
        """
        logger.info(
            f"{LOG_PREFIX} Getting conversation summary",
            extra={"conversation_id": conversation_id, "operation": "get_summary"}
        )
        
        logs = await self.audit_logger.query_logs_by_conversation(conversation_id)

        if not logs:
            logger.info(
                f"{LOG_PREFIX} No logs found for conversation summary",
                extra={"conversation_id": conversation_id}
            )
            return None

        statistics = self._calculate_statistics(logs)

        # Get first and last timestamps
        timestamps = [log.get('timestamp', '') for log in logs if log.get('timestamp')]
        timestamps.sort()

        summary = {
            "conversation_id": conversation_id,
            "total_requests": len(logs),
            "started_at": timestamps[0] if timestamps else None,
            "ended_at": timestamps[-1] if timestamps else None,
            "statistics": statistics
        }
        
        logger.info(
            f"{LOG_PREFIX} Conversation summary retrieved",
            extra={
                "conversation_id": conversation_id,
                "total_requests": len(logs),
                "duration_range": f"{timestamps[0]} to {timestamps[-1]}" if timestamps else "N/A"
            }
        )

        return summary
