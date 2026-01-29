"""
Tool: list_orders
List recent orders from DynamoDB demo-orders table
"""

import os
import logging
from typing import Dict, List, Optional
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def list_orders(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10
) -> Dict:
    """
    List recent orders with optional filters

    Args:
        customer_id: Optional filter by customer ID
        status: Optional filter by order status (completed, pending, refunded)
        limit: Maximum number of orders to return (default 10, max 50)

    Returns:
        Dictionary with orders list and metadata

    Security Validations:
    - READ operation (minimal restrictions)
    - Rate limiting may apply

    Business Logic:
    - Returns most recent orders first
    - Limited to 50 orders max to prevent excessive data transfer
    - Converts Decimal types to float for JSON serialization
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Enforce reasonable limit
    if limit > 50:
        limit = 50
    elif limit < 1:
        limit = 10

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    logger.info(
        "Tool initiated: list_orders",
        extra={
            "tool": "list_orders",
            "table": table_name,
            "customer_id": customer_id,
            "status": status,
            "limit": limit
        }
    )

    try:
        # Query or scan based on filters
        if customer_id:
            # Query by customer_id using GSI (if exists)
            # Fallback to scan if GSI not available
            response = table.scan(
                FilterExpression='customer_id = :cid',
                ExpressionAttributeValues={':cid': customer_id},
                Limit=limit
            )
        else:
            # Scan all orders
            response = table.scan(Limit=limit)

        items = response.get('Items', [])

        # Apply status filter if provided
        if status:
            items = [item for item in items if item.get('status') == status]

        # Sort by created_at descending (most recent first)
        items.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        # Limit results
        items = items[:limit]

        # Convert Decimal to float for JSON serialization
        orders = []
        for item in items:
            order = {}
            for key, value in item.items():
                if isinstance(value, Decimal):
                    order[key] = float(value)
                else:
                    order[key] = value
            orders.append(order)

        result = {
            "status": "success",
            "count": len(orders),
            "orders": orders,
            "filters": {
                "customer_id": customer_id,
                "status": status,
                "limit": limit
            }
        }

        # Log response preview (first 10 orders)
        preview_orders = orders[:10]
        logger.info(
            "Tool response: list_orders",
            extra={
                "tool": "list_orders",
                "count": len(orders),
                "preview_count": len(preview_orders),
                "preview": [{"order_id": o.get("order_id"), "amount": o.get("amount"), "status": o.get("status")} for o in preview_orders]
            }
        )

        logger.info(
            "Tool completed: list_orders",
            extra={
                "tool": "list_orders",
                "count": len(orders),
                "customer_id": customer_id,
                "status": status
            }
        )

        return result

    except Exception as e:
        logger.error(
            "Tool exception: list_orders",
            extra={
                "tool": "list_orders",
                "table": table_name,
                "customer_id": customer_id,
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True  # Include full stack trace
        )
        raise ValueError(f"Failed to list orders: {str(e)}")
