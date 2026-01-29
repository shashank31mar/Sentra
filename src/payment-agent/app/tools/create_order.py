"""
Tool: create_order
Create a new order in DynamoDB demo-orders table

Reversible: Yes (via delete_order)
Workstream: 12 - Multi-Agent Workflow (Milestone 5)
"""

import os
import logging
import uuid
from typing import Dict, List
from datetime import datetime

import boto3
from decimal import Decimal

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)

# Structured logging prefix for CloudWatch filtering
LOG_PREFIX = "[WS12-M5-CREATE-ORDER]"


@secured_tool
def create_order(
    customer_id: str,
    customer_name: str,
    amount: float,
    items: List[Dict]
) -> Dict:
    """
    Create a new order in DynamoDB

    Args:
        customer_id: Customer identifier
        customer_name: Customer name
        amount: Order total amount
        items: List of order items

    Returns:
        Created order details with order_id

    Security Validations:
    - Policy: order-policy-v1
    - Session context: authorization_level checked

    Reversible: Yes - can be deleted via delete_order tool
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    # Generate order ID
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    created_at = datetime.utcnow().isoformat()

    logger.info(
        f"{LOG_PREFIX} Creating new order",
        extra={
            "tool": "create_order",
            "table": table_name,
            "order_id": order_id,
            "customer_id": customer_id,
            "amount": amount,
            "items_count": len(items),
            "workstream": "12",
            "milestone": "5"
        }
    )

    # Validate amount
    if amount <= 0:
        error_msg = f"Order amount must be positive, got ${amount:.2f}"
        logger.error(error_msg, extra={"amount": amount})
        raise ValueError(error_msg)

    # Build order item
    order = {
        'order_id': order_id,
        'customer_id': customer_id,
        'customer_name': customer_name,
        'amount': Decimal(str(amount)),
        'items': items,
        'status': 'pending',
        'created_at': created_at
    }

    # Create order in DynamoDB
    table.put_item(Item=order)

    result = {
        "status": "created",
        "order_id": order_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "amount": amount,
        "items_count": len(items),
        "created_at": created_at
    }

    logger.info(
        f"{LOG_PREFIX} Order created successfully",
        extra={
            "tool": "create_order",
            "order_id": order_id,
            "customer_id": customer_id,
            "amount": amount,
            "status": "created"
        }
    )

    logger.info(
        f"{LOG_PREFIX} Tool completed: create_order",
        extra={
            "tool": "create_order",
            "order_id": order_id,
            "status": "created"
        }
    )

    return result
