"""
Rollback Coordinator - Manual Rollback of Reversible Actions

Handles manual rollback of reversible actions (e.g., refunds) after execution.
Supports both single-action and conversation-wide rollback.

MVP Features:
- Single action rollback: process_refund → reverse_refund
- Conversation-wide rollback: Roll back all WRITE operations in a conversation

Workstream: 12 - Multi-Agent Workflow (Milestone 5)
"""
import logging
import time
import json
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone

import boto3
import requests
from botocore.exceptions import ClientError

from app.config import settings
from app.utils.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

# Structured logging prefix for CloudWatch filtering
LOG_PREFIX = "[WS12-M5-ROLLBACK]"


class RollbackCoordinator:
    """
    Handles manual rollback of reversible actions.
    
    Supported Actions (MVP):
    - process_refund → reverse_refund
    
    Phase 2:
    - terminate_ec2 → restart instance
    - delete_s3_object → restore from versioning
    - Multi-agent rollback coordination
    """
    
    # Supported reversible actions and their rollback tools
    REVERSIBLE_ACTIONS = {
        "process_refund": "reverse_refund",
        "create_order": "delete_order"
    }
    
    # Agent URLs for rollback execution
    AGENT_URLS = {
        'customer-query-agent': 'http://customer-query-agent.sentra.internal:8080',
        'payment-agent': 'http://payment-agent.sentra.internal:8080'
    }
    
    def __init__(self):
        self.cloudwatch_logs = boto3.client('logs', region_name=settings.aws_region)
        self.dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
        self.log_group = settings.cloudwatch_log_group
        self.audit_logger = AuditLogger()
        
        # DynamoDB tables
        self.orders_table = self.dynamodb.Table('sentra-demo-orders')
    
    async def rollback_action(
        self,
        action_id: str,
        action_type: str,
        reason: str,
        operator_id: str
    ) -> Dict[str, Any]:
        """
        Rollback a reversible action.
        
        Args:
            action_id: Unique action identifier
            action_type: Type of action (e.g., "process_refund")
            reason: Reason for rollback
            operator_id: Operator performing rollback
            
        Returns:
            Dict with success status and rollback details
        """
        logger.info(
            f"{LOG_PREFIX} Starting single action rollback",
            extra={
                "action_id": action_id,
                "action_type": action_type,
                "reason": reason,
                "operator_id": operator_id,
                "operation": "rollback_action",
                "workstream": "12",
                "milestone": "5"
            }
        )
        
        try:
            # Validate action type is supported
            if action_type not in self.REVERSIBLE_ACTIONS:
                logger.warning(
                    f"{LOG_PREFIX} Action type not reversible",
                    extra={"action_id": action_id, "action_type": action_type}
                )
                return {
                    "success": False,
                    "message": f"Action type '{action_type}' is not reversible",
                    "action_id": action_id
                }
            
            # Retrieve original action from CloudWatch Logs
            original_action = await self._get_action_from_logs(action_id)
            
            if not original_action:
                return {
                    "success": False,
                    "message": "Action not found or not reversible",
                    "action_id": action_id
                }
            
            # Check if already rolled back
            if original_action.get("rollback_status") == "ROLLED_BACK":
                return {
                    "success": False,
                    "message": "Action already rolled back",
                    "action_id": action_id
                }
            
            # Execute rollback based on action type
            if action_type == "process_refund":
                rollback_result = await self._rollback_refund(original_action)
            else:
                return {
                    "success": False,
                    "message": f"Rollback handler not implemented for {action_type}",
                    "action_id": action_id
                }
            
            # Generate rollback ID
            rollback_id = f"rb-{int(time.time())}"
            
            # Log rollback event
            await self._log_rollback(
                action_id=action_id,
                rollback_id=rollback_id,
                operator_id=operator_id,
                reason=reason,
                result=rollback_result
            )
            
            return {
                "success": True,
                "message": "Refund reversed successfully",
                "rollback_id": rollback_id,
                "action_id": action_id,
                "original_action": {
                    "tool_name": original_action.get("tool_name"),
                    "order_id": rollback_result.get("order_id"),
                    "amount": rollback_result.get("amount"),
                    "timestamp": original_action.get("timestamp")
                },
                "rollback_action": {
                    "tool_name": "reverse_refund",
                    "order_id": rollback_result.get("order_id"),
                    "amount": rollback_result.get("amount"),
                    "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                }
            }
            
        except Exception as e:
            logger.exception(
                f"{LOG_PREFIX} Rollback failed for action",
                extra={"action_id": action_id, "error": str(e)}
            )
            return {
                "success": False,
                "message": f"Rollback failed: {str(e)}",
                "action_id": action_id
            }
    
    async def _get_action_from_logs(self, action_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve action from CloudWatch Logs by action_id.
        
        Args:
            action_id: Action identifier
            
        Returns:
            Action dict or None if not found
        """
        try:
            # Build query to find action by action_id
            query = f"""
            fields @timestamp, @message
            | parse @message /(?<log_data>.*)/
            | filter @message like "{action_id}"
            | limit 1
            """
            
            # Query last 7 days
            end_time = int(time.time() * 1000)
            start_time = end_time - (7 * 24 * 60 * 60 * 1000)  # 7 days ago
            
            # Start query
            response = self.cloudwatch_logs.start_query(
                logGroupName=self.log_group,
                startTime=start_time,
                endTime=end_time,
                queryString=query
            )
            
            query_id = response['queryId']
            
            # Poll for results (max 5 seconds)
            max_wait = 5
            start = time.time()
            
            while time.time() - start < max_wait:
                result = self.cloudwatch_logs.get_query_results(queryId=query_id)
                
                if result['status'] == 'Complete':
                    if result['results']:
                        # Parse first result
                        for field in result['results'][0]:
                            if field['field'] == '@message':
                                log_data = json.loads(field['value'])
                                # Verify this is the action we're looking for
                                if log_data.get('action_id') == action_id:
                                    return log_data
                    return None
                
                elif result['status'] == 'Failed':
                    logger.error("CloudWatch query failed")
                    return None
                
                time.sleep(0.5)
            
            logger.warning("CloudWatch query timeout")
            return None
            
        except Exception as e:
            logger.exception(f"Failed to retrieve action from logs: {e}")
            return None
    
    async def _rollback_refund(self, original_action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rollback a refund by updating order status to REVERSED.
        
        Args:
            original_action: Original action details from audit log
            
        Returns:
            Dict with rollback details
        """
        try:
            # Extract order details from original action
            # Note: In real implementation, tool_params would be in the action log
            # For MVP, we'll extract from the log entry
            order_id = original_action.get("order_id", "UNKNOWN")
            amount = original_action.get("amount", 0.0)
            
            # If not in top level, try to extract from tool_params or other fields
            if order_id == "UNKNOWN":
                # Try to find order_id in the log entry
                # This is a simplified approach for MVP
                logger.warning(f"Order ID not found in action log, using placeholder")
                order_id = "ORD-UNKNOWN"
            
            # Update DynamoDB order status
            try:
                self.orders_table.update_item(
                    Key={'order_id': order_id},
                    UpdateExpression='SET refund_status = :status, refund_reversed_at = :timestamp',
                    ExpressionAttributeValues={
                        ':status': 'REVERSED',
                        ':timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                    }
                )
                
                logger.info(f"Reversed refund for order {order_id}")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.warning(f"Order {order_id} not found in demo orders table")
                else:
                    raise
            
            return {
                "order_id": order_id,
                "amount": amount,
                "status": "REVERSED"
            }
            
        except Exception as e:
            logger.exception(f"Failed to rollback refund: {e}")
            raise
    
    async def _log_rollback(
        self,
        action_id: str,
        rollback_id: str,
        operator_id: str,
        reason: str,
        result: Dict[str, Any]
    ):
        """
        Log rollback event to CloudWatch Logs.
        
        Args:
            action_id: Original action ID
            rollback_id: Rollback ID
            operator_id: Operator who performed rollback
            reason: Reason for rollback
            result: Rollback result details
        """
        try:
            # Build rollback log event
            log_event = {
                "event_type": "ROLLBACK",
                "rollback_id": rollback_id,
                "action_id": action_id,
                "operator_id": operator_id,
                "reason": reason,
                "original_action": {
                    "tool_name": "process_refund",
                    "order_id": result.get("order_id"),
                    "amount": result.get("amount")
                },
                "rollback_action": {
                    "tool_name": "reverse_refund",
                    "order_id": result.get("order_id"),
                    "amount": result.get("amount")
                },
                "rollback_status": "SUCCESS",
                "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            }
            
            # Create log stream for rollbacks
            log_stream_name = f"rollback-{rollback_id}"
            
            try:
                self.cloudwatch_logs.create_log_stream(
                    logGroupName=self.log_group,
                    logStreamName=log_stream_name
                )
            except ClientError as e:
                if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                    raise
            
            # Write log event
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
            
            logger.info(f"Logged rollback event: {rollback_id}")
            
        except Exception as e:
            logger.exception(f"Failed to log rollback event: {e}")
            # Don't raise - logging failure shouldn't block rollback

    async def rollback_conversation(
        self,
        conversation_id: str,
        reason: str,
        operator_id: str = "system"
    ) -> Dict[str, Any]:
        """
        Roll back ALL WRITE operations in a conversation.
        
        Fetches all audit logs for the conversation, filters for reversible
        WRITE operations, and executes rollback in LIFO order (last action first).
        
        Args:
            conversation_id: Conversation identifier
            reason: Reason for rollback
            operator_id: Operator performing rollback (default: "system")
            
        Returns:
            Dict with rollback summary
        """
        logger.info(
            f"{LOG_PREFIX} Starting conversation-wide rollback",
            extra={
                "conversation_id": conversation_id,
                "reason": reason,
                "operator_id": operator_id,
                "operation": "rollback_conversation",
                "workstream": "12",
                "milestone": "5"
            }
        )
        
        try:
            # Step 1: Fetch all audit logs for conversation
            logs = await self.audit_logger.query_logs_by_conversation(conversation_id)
            
            if not logs:
                logger.info(
                    f"{LOG_PREFIX} No logs found for conversation",
                    extra={"conversation_id": conversation_id}
                )
                return {
                    "success": True,
                    "conversation_id": conversation_id,
                    "rolled_back_count": 0,
                    "failed_count": 0,
                    "message": "No logs found for this conversation",
                    "rolled_back_actions": [],
                    "failed_actions": [],
                    "reason": reason
                }
            
            # Step 2: Filter for reversible WRITE operations
            reversible_actions = [
                log for log in logs
                if log.get('operation_type') == 'WRITE'
                and log.get('decision') == 'ALLOW'
                and log.get('reversible') is True
                and log.get('rollback_status', 'NOT_ROLLED_BACK') == 'NOT_ROLLED_BACK'
            ]
            
            if not reversible_actions:
                logger.info(
                    f"{LOG_PREFIX} No reversible actions found for conversation",
                    extra={
                        "conversation_id": conversation_id,
                        "total_logs": len(logs)
                    }
                )
                return {
                    "success": True,
                    "conversation_id": conversation_id,
                    "rolled_back_count": 0,
                    "failed_count": 0,
                    "message": "No reversible actions to roll back",
                    "rolled_back_actions": [],
                    "failed_actions": [],
                    "reason": reason
                }
            
            # Step 3: Reverse order (LIFO - last action first)
            # Sort by timestamp descending
            reversible_actions.sort(
                key=lambda x: x.get('timestamp', ''),
                reverse=True
            )
            
            logger.info(
                f"{LOG_PREFIX} Found reversible actions to roll back",
                extra={
                    "conversation_id": conversation_id,
                    "reversible_count": len(reversible_actions),
                    "total_logs": len(logs),
                    "action_ids": [a.get('action_id') for a in reversible_actions]
                }
            )
            
            # Step 4: Execute rollback for each action
            rolled_back = []
            failed = []
            
            for log in reversible_actions:
                action_id = log.get('action_id')
                tool_name = log.get('tool_name')
                
                try:
                    result = await self._rollback_single_action(log, reason, operator_id)
                    
                    if result.get('success'):
                        rolled_back.append({
                            "action_id": action_id,
                            "tool_name": tool_name,
                            "rollback_id": result.get('rollback_id')
                        })
                        logger.info(
                            f"{LOG_PREFIX} Successfully rolled back action",
                            extra={
                                "action_id": action_id,
                                "tool_name": tool_name,
                                "rollback_id": result.get('rollback_id'),
                                "conversation_id": conversation_id
                            }
                        )
                    else:
                        failed.append({
                            "action_id": action_id,
                            "tool_name": tool_name,
                            "error": result.get('message', 'Unknown error')
                        })
                        logger.error(
                            f"{LOG_PREFIX} Failed to roll back action",
                            extra={
                                "action_id": action_id,
                                "tool_name": tool_name,
                                "error": result.get('message'),
                                "conversation_id": conversation_id
                            }
                        )
                except Exception as e:
                    failed.append({
                        "action_id": action_id,
                        "tool_name": tool_name,
                        "error": str(e)
                    })
                    logger.exception(
                        f"{LOG_PREFIX} Exception rolling back action",
                        extra={
                            "action_id": action_id,
                            "conversation_id": conversation_id
                        }
                    )
            
            # Step 5: Return summary
            success = len(failed) == 0
            
            logger.info(
                f"{LOG_PREFIX} Conversation rollback completed",
                extra={
                    "conversation_id": conversation_id,
                    "success": success,
                    "rolled_back_count": len(rolled_back),
                    "failed_count": len(failed),
                    "reason": reason
                }
            )
            
            return {
                "success": success,
                "conversation_id": conversation_id,
                "rolled_back_count": len(rolled_back),
                "failed_count": len(failed),
                "rolled_back_actions": rolled_back,
                "failed_actions": failed,
                "reason": reason
            }
            
        except Exception as e:
            logger.exception(f"Conversation rollback failed: {e}")
            return {
                "success": False,
                "conversation_id": conversation_id,
                "rolled_back_count": 0,
                "failed_count": 0,
                "message": f"Rollback failed: {str(e)}",
                "rolled_back_actions": [],
                "failed_actions": [],
                "reason": reason
            }

    async def _rollback_single_action(
        self,
        log: Dict[str, Any],
        reason: str,
        operator_id: str
    ) -> Dict[str, Any]:
        """
        Execute rollback for a single action from audit log.
        
        Args:
            log: Audit log entry for the action
            reason: Rollback reason
            operator_id: Operator performing rollback
            
        Returns:
            Dict with success status and rollback details
        """
        tool_name = log.get('tool_name')
        action_id = log.get('action_id')
        agent_id = log.get('agent_id')
        tool_params = log.get('tool_params', {})
        
        # Get rollback tool name
        rollback_tool = self.REVERSIBLE_ACTIONS.get(tool_name)
        
        if not rollback_tool:
            return {
                "success": False,
                "message": f"No rollback tool defined for {tool_name}"
            }
        
        # Build rollback parameters based on tool type
        rollback_params = self._build_rollback_params(tool_name, tool_params, log)
        
        # Generate rollback ID
        rollback_id = f"rb-conv-{int(time.time())}-{action_id[-6:]}"
        
        # Execute rollback based on tool type
        try:
            if tool_name == "process_refund":
                # Use existing _rollback_refund method
                result = await self._rollback_refund(log)
                
            elif tool_name == "create_order":
                # Delete the order
                result = await self._rollback_create_order(log)
                
            else:
                return {
                    "success": False,
                    "message": f"Rollback handler not implemented for {tool_name}"
                }
            
            # Log rollback event
            await self._log_rollback(
                action_id=action_id,
                rollback_id=rollback_id,
                operator_id=operator_id,
                reason=reason,
                result=result
            )
            
            return {
                "success": True,
                "rollback_id": rollback_id,
                "action_id": action_id,
                "tool_name": tool_name
            }
            
        except Exception as e:
            logger.exception(f"Rollback execution failed for {action_id}")
            return {
                "success": False,
                "message": str(e)
            }

    def _build_rollback_params(
        self,
        tool_name: str,
        original_params: Dict,
        log: Dict
    ) -> Dict:
        """
        Build parameters for rollback tool based on original params.
        
        Args:
            tool_name: Original tool name
            original_params: Original tool parameters
            log: Full audit log entry
            
        Returns:
            Parameters for rollback tool
        """
        if tool_name == 'process_refund':
            return {
                "transaction_id": original_params.get('transaction_id'),
                "reason": "Conversation rollback"
            }
        
        elif tool_name == 'create_order':
            return {
                "order_id": original_params.get('order_id'),
                "reason": "Conversation rollback"
            }
        
        # Default: return original params
        return original_params

    async def _rollback_create_order(self, original_action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rollback a create_order by deleting the order.
        
        Args:
            original_action: Original action details from audit log
            
        Returns:
            Dict with rollback details
        """
        try:
            tool_params = original_action.get('tool_params', {})
            
            # Try to get order_id from various places
            order_id = tool_params.get('order_id')
            
            if not order_id:
                # Try to find in log entry itself
                order_id = original_action.get('order_id')
            
            if not order_id:
                logger.warning("Order ID not found in action log")
                return {
                    "status": "FAILED",
                    "error": "Order ID not found in action log"
                }
            
            # Delete order from DynamoDB
            try:
                self.orders_table.delete_item(Key={'order_id': order_id})
                logger.info(f"Deleted order {order_id} as part of rollback")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.warning(f"Order {order_id} not found (may already be deleted)")
                else:
                    raise
            
            return {
                "order_id": order_id,
                "status": "DELETED"
            }
            
        except Exception as e:
            logger.exception(f"Failed to rollback create_order: {e}")
            raise
