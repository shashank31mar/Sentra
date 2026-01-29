"""
Tool: delete_order
Delete an order from DynamoDB (rollback handler for create_order)

Workstream: 12 - Multi-Agent Workflow (Milestone 5)
"""

import os
import logging
from typing import Dict
from datetime import datetime

import boto3

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)

# Structured logging prefix for CloudWatch filtering
LOG_PREFIX = "[WS12-M5-DELETE-ORDER]"


@secured_tool
def delete_order(order_id: str, reason: str) -> Dict:
    """
    Delete an order from DynamoDB (rollback for create_order)

    Args:
        order_id: Order identifier to delete
        reason: Reason for deletion (rollback reason)

    Returns:
        Deletion confirmation details

    Security Validations:
    - Policy: order-policy-v1 (requires manager authorization)

    Business Logic:
    - Order must exist
    - Order must be in 'pending' status (cannot delete completed orders)
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    logger.info(
        f"{LOG_PREFIX} Deleting order (rollback operation)",
        extra={
            "tool": "delete_order",
            "table": table_name,
            "order_id": order_id,
            "reason": reason,
            "workstream": "12",
            "milestone": "5"
        }
    )

    # Get order first to validate
    response = table.get_item(Key={'order_id': order_id})
    order = response.get('Item')

    if not order:
        error_msg = f"Order {order_id} not found"
        logger.error(error_msg, extra={"order_id": order_id})
        raise ValueError(error_msg)

    # Validate order status - only pending orders can be deleted
    order_status = order.get('status')
    if order_status not in ['pending', 'created']:
        error_msg = f"Order {order_id} has status '{order_status}', only pending orders can be deleted"
        logger.error(error_msg, extra={"order_id": order_id, "status": order_status})
        raise ValueError(error_msg)

    deleted_at = datetime.utcnow().isoformat()

    # Delete order from DynamoDB
    table.delete_item(Key={'order_id': order_id})

    result = {
        "status": "deleted",
        "order_id": order_id,
        "customer_id": order.get('customer_id'),
        "customer_name": order.get('customer_name'),
        "amount": float(order.get('amount', 0)),
        "reason": reason,
        "deleted_at": deleted_at
    }

    logger.info(
        f"{LOG_PREFIX} Order deleted successfully",
        extra={
            "tool": "delete_order",
            "order_id": order_id,
            "customer_id": result.get("customer_id"),
            "amount": result.get("amount"),
            "reason": reason
        }
    )

    logger.info(
        f"{LOG_PREFIX} Tool completed: delete_order",
        extra={
            "tool": "delete_order",
            "order_id": order_id,
            "status": "deleted"
        }
    )

    return result
