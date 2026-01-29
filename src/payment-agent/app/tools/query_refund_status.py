"""
Tool: query_refund_status
Query refund status for an order from DynamoDB demo-orders table
"""

import os
import logging
from typing import Dict, Optional

import boto3

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def query_refund_status(order_id: str) -> Dict:
    """
    Query refund status for an order

    Args:
        order_id: Order identifier

    Returns:
        Refund details or status indicating no refund

    Security Validations:
    - None (single record lookup is safe)
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    logger.info(
        "Tool initiated: query_refund_status",
        extra={
            "tool": "query_refund_status",
            "table": table_name,
            "order_id": order_id
        }
    )

    # Get order by order_id
    response = table.get_item(Key={'order_id': order_id})
    order = response.get('Item')

    if not order:
        logger.warning(
            "Order not found",
            extra={"order_id": order_id}
        )
        return {
            "order_id": order_id,
            "status": "not_found",
            "message": f"Order {order_id} not found"
        }

    # Extract refund details
    refund_details = {
        "order_id": order_id,
        "customer_id": order.get('customer_id'),
        "customer_name": order.get('customer_name'),
        "order_amount": float(order.get('amount', 0)),
        "order_status": order.get('status'),
        "refund_amount": float(order.get('refund_amount', 0)) if order.get('refund_amount') else None,
        "refund_date": order.get('refund_date'),
        "refund_status": order.get('refund_status', 'not_refunded'),
        "transaction_id": order.get('transaction_id')
    }

    # Add rollback details if present
    if 'rollback_reason' in order:
        refund_details['rollback_reason'] = order.get('rollback_reason')
        refund_details['rollback_date'] = order.get('rollback_date')

    logger.info(
        "Tool response: query_refund_status",
        extra={
            "tool": "query_refund_status",
            "order_id": order_id,
            "refund_status": refund_details['refund_status'],
            "refund_amount": refund_details.get('refund_amount'),
            "transaction_id": refund_details.get('transaction_id')
        }
    )

    logger.info(
        "Tool completed: query_refund_status",
        extra={
            "tool": "query_refund_status",
            "order_id": order_id,
            "refund_status": refund_details['refund_status']
        }
    )

    return refund_details
