"""
Tool: query_orders
Query orders from DynamoDB demo-orders table with optional filters
"""

import os
import logging
from typing import Dict, List, Optional
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def query_orders(filters: Optional[Dict] = None) -> List[Dict]:
    """
    Query orders from DynamoDB demo-orders table

    Args:
        filters: Dict with optional keys:
            - customer_id: str
            - status: str (completed, pending, cancelled)
            - min_amount: float
            - max_amount: float
            - limit: int (default 100, max 1000)

    Returns:
        List of order records

    Security Validations:
    - Sigma rule: DATA_EXFILTRATION_MASS_QUERY
    """
    filters = filters or {}

    # Get environment configuration
    table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    # Apply limit (default 100, max 1000)
    limit = filters.get('limit', 100)
    limit = min(limit, 1000)  # Enforce max limit

    logger.info(
        "Tool initiated: query_orders",
        extra={
            "tool": "query_orders",
            "table": table_name,
            "filters": filters,
            "limit": limit
        }
    )

    # Use GSI if querying by customer_id
    if 'customer_id' in filters:
        # Query using customer-index GSI
        query_params = {
            'IndexName': 'customer-index',
            'KeyConditionExpression': Key('customer_id').eq(filters['customer_id']),
            'Limit': limit
        }

        # Add filter expressions for other filters
        filter_expressions = []

        if 'status' in filters:
            filter_expressions.append(Attr('status').eq(filters['status']))

        if 'min_amount' in filters:
            filter_expressions.append(Attr('amount').gte(Decimal(str(filters['min_amount']))))

        if 'max_amount' in filters:
            filter_expressions.append(Attr('amount').lte(Decimal(str(filters['max_amount']))))

        if filter_expressions:
            combined_filter = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined_filter = combined_filter & expr
            query_params['FilterExpression'] = combined_filter

        response = table.query(**query_params)
        items = response.get('Items', [])

    else:
        # Scan table (no customer_id specified)
        scan_params = {'Limit': limit}

        # Build filter expressions
        filter_expressions = []

        if 'status' in filters:
            filter_expressions.append(Attr('status').eq(filters['status']))

        if 'min_amount' in filters:
            filter_expressions.append(Attr('amount').gte(Decimal(str(filters['min_amount']))))

        if 'max_amount' in filters:
            filter_expressions.append(Attr('amount').lte(Decimal(str(filters['max_amount']))))

        if filter_expressions:
            combined_filter = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined_filter = combined_filter & expr
            scan_params['FilterExpression'] = combined_filter

        response = table.scan(**scan_params)
        items = response.get('Items', [])

    # Convert Decimal to float for JSON serialization
    items = _convert_decimals(items)

    # Log response preview (first 10 orders)
    preview_items = items[:10]
    logger.info(
        "Tool response: query_orders",
        extra={
            "tool": "query_orders",
            "count": len(items),
            "preview_count": len(preview_items),
            "preview": [{"order_id": o.get("order_id"), "amount": o.get("amount"), "status": o.get("status")} for o in preview_items]
        }
    )

    logger.info(
        "Tool completed: query_orders",
        extra={
            "tool": "query_orders",
            "table": table_name,
            "count": len(items)
        }
    )

    return items


def _convert_decimals(items: List[Dict]) -> List[Dict]:
    """Convert Decimal values to float for JSON serialization"""
    result = []
    for item in items:
        converted = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                converted[key] = float(value)
            else:
                converted[key] = value
        result.append(converted)
    return result
