"""
Tool: reverse_refund
Reverse a previously processed refund (manual rollback)
"""

import os
import logging
from typing import Dict
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def reverse_refund(transaction_id: str, reason: str) -> Dict:
    """
    Reverse a refund (manual rollback operation)

    Args:
        transaction_id: Transaction identifier to reverse
        reason: Rollback reason

    Returns:
        Rollback confirmation details

    Security Validations:
    - Policy: rollback-policy-v1 (requires director authorization)

    Business Logic:
    - Transaction must exist (found via GSI)
    - Order must be in 'refunded' status
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    logger.info(
        "Tool initiated: reverse_refund",
        extra={
            "tool": "reverse_refund",
            "table": table_name,
            "transaction_id": transaction_id,
            "reason": reason
        }
    )

    # Find order by transaction_id using GSI
    try:
        response = table.query(
            IndexName='transaction-index',
            KeyConditionExpression=Key('transaction_id').eq(transaction_id)
        )
    except Exception as e:
        # GSI might not be ready yet or other error
        error_msg = f"Failed to query transaction-index GSI: {str(e)}"
        logger.error(
            error_msg,
            extra={
                "transaction_id": transaction_id,
                "error": str(e)
            }
        )
        raise ValueError(f"Transaction lookup failed: {str(e)}")

    items = response.get('Items', [])

    if not items:
        error_msg = f"Transaction {transaction_id} not found"
        logger.error(error_msg, extra={"transaction_id": transaction_id})
        raise ValueError(error_msg)

    if len(items) > 1:
        error_msg = f"Multiple orders found for transaction {transaction_id} (data integrity issue)"
        logger.error(
            error_msg,
            extra={
                "transaction_id": transaction_id,
                "count": len(items)
            }
        )
        raise ValueError(error_msg)

    order = items[0]
    order_id = order['order_id']

    # Validate order is in refunded status
    if order.get('refund_status') != 'refunded':
        error_msg = f"Order {order_id} is not in 'refunded' status, cannot reverse"
        logger.error(
            error_msg,
            extra={
                "order_id": order_id,
                "transaction_id": transaction_id,
                "current_status": order.get('refund_status')
            }
        )
        raise ValueError(error_msg)

    rollback_date = datetime.utcnow().isoformat()

    # Reverse refund by removing refund fields and adding rollback metadata
    logger.info(
        "Updating order to reverse refund",
        extra={
            "order_id": order_id,
            "transaction_id": transaction_id
        }
    )

    table.update_item(
        Key={'order_id': order_id},
        UpdateExpression='REMOVE refund_amount, refund_date, transaction_id SET refund_status = :status, rollback_reason = :reason, rollback_date = :date',
        ExpressionAttributeValues={
            ':status': 'refund_reversed',
            ':reason': reason,
            ':date': rollback_date
        }
    )

    result = {
        "status": "reversed",
        "order_id": order_id,
        "transaction_id": transaction_id,
        "original_refund_amount": float(order.get('refund_amount', 0)),
        "rollback_reason": reason,
        "rollback_date": rollback_date,
        "customer_id": order.get('customer_id'),
        "customer_name": order.get('customer_name')
    }

    logger.info(
        "Tool response: reverse_refund",
        extra={
            "tool": "reverse_refund",
            "order_id": order_id,
            "transaction_id": transaction_id,
            "original_refund_amount": result.get("original_refund_amount"),
            "rollback_date": rollback_date
        }
    )

    logger.info(
        "Tool completed: reverse_refund",
        extra={
            "tool": "reverse_refund",
            "order_id": order_id,
            "transaction_id": transaction_id,
            "rollback_date": rollback_date
        }
    )

    return result
