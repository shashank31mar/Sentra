"""
Tool: process_refund
Process a refund for an order in DynamoDB demo-orders table
"""

import os
import logging
import uuid
from typing import Dict
from datetime import datetime

import boto3
from decimal import Decimal

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def process_refund(order_id: str, amount: float, reason: str) -> Dict:
    """
    Process a refund for an order

    Args:
        order_id: Order identifier
        amount: Refund amount in dollars
        reason: Refund reason

    Returns:
        Transaction details

    Security Validations:
    - Policy: refund-limit-policy-v1 (manager limit $200)
    - Sigma rule: BUSINESS_RULE_REFUND_LIMIT
    - Session context: authorization_level checked

    Business Logic:
    - Order must exist
    - Order status must be "completed"
    - Refund amount must not exceed order total
    - Order must not already be refunded
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    logger.info(
        "Tool initiated: process_refund",
        extra={
            "tool": "process_refund",
            "table": table_name,
            "order_id": order_id,
            "amount": amount,
            "reason": reason
        }
    )

    # Get order
    response = table.get_item(Key={'order_id': order_id})
    order = response.get('Item')

    if not order:
        error_msg = f"Order {order_id} not found"
        logger.error(error_msg, extra={"order_id": order_id})
        raise ValueError(error_msg)

    # Validate order status
    order_status = order.get('status')
    if order_status != 'completed':
        error_msg = f"Order {order_id} has status '{order_status}', must be 'completed' to process refund"
        logger.error(error_msg, extra={"order_id": order_id, "status": order_status})
        raise ValueError(error_msg)

    # Check if already refunded
    if order.get('refund_status') == 'refunded':
        error_msg = f"Order {order_id} has already been refunded"
        logger.error(error_msg, extra={"order_id": order_id})
        raise ValueError(error_msg)

    # Validate refund amount
    order_amount = float(order.get('amount', 0))
    if amount > order_amount:
        error_msg = f"Refund amount ${amount:.2f} exceeds order total ${order_amount:.2f}"
        logger.error(
            error_msg,
            extra={
                "order_id": order_id,
                "refund_amount": amount,
                "order_amount": order_amount
            }
        )
        raise ValueError(error_msg)

    if amount <= 0:
        error_msg = f"Refund amount must be positive, got ${amount:.2f}"
        logger.error(error_msg, extra={"order_id": order_id, "amount": amount})
        raise ValueError(error_msg)

    # Generate transaction ID
    transaction_id = f"txn-{uuid.uuid4().hex[:12]}"
    refund_date = datetime.utcnow().isoformat()

    # Update order with refund details
    # Note: Using Decimal for DynamoDB numeric values
    logger.info(
        "Updating order with refund details",
        extra={
            "order_id": order_id,
            "transaction_id": transaction_id,
            "refund_amount": amount
        }
    )

    table.update_item(
        Key={'order_id': order_id},
        UpdateExpression='SET refund_amount = :amount, refund_date = :date, refund_status = :status, transaction_id = :txn',
        ExpressionAttributeValues={
            ':amount': Decimal(str(amount)),  # Convert to Decimal for DynamoDB
            ':date': refund_date,
            ':status': 'refunded',
            ':txn': transaction_id
        }
    )

    result = {
        "status": "success",
        "transaction_id": transaction_id,
        "order_id": order_id,
        "refund_amount": amount,
        "refund_date": refund_date,
        "reason": reason,
        "customer_id": order.get('customer_id'),
        "customer_name": order.get('customer_name')
    }

    logger.info(
        "Tool response: process_refund",
        extra={
            "tool": "process_refund",
            "transaction_id": transaction_id,
            "order_id": order_id,
            "refund_amount": amount,
            "customer_id": result.get("customer_id")
        }
    )

    logger.info(
        "Tool completed: process_refund",
        extra={
            "tool": "process_refund",
            "order_id": order_id,
            "transaction_id": transaction_id,
            "refund_amount": amount
        }
    )

    return result
