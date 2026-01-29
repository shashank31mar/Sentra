"""
Tool: query_customers
Query customers from DynamoDB demo-customers table with optional filters
"""

import os
import logging
from typing import Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def query_customers(filters: Optional[Dict] = None) -> List[Dict]:
    """
    Query customers from DynamoDB demo-customers table

    Args:
        filters: Dict with optional keys:
            - state: str (e.g., "CA")
            - name_contains: str
            - email_contains: str
            - limit: int (default 100, max 1000)

    Returns:
        List of customer records

    Security Validations:
    - Sigma rule: DATA_EXFILTRATION_MASS_QUERY (no LIMIT = DENY)
    - Sigma rule: PII_SSN_EXPOSURE (SSN in response = DENY)
    """
    filters = filters or {}

    # Get environment configuration
    table_name = os.environ.get('DEMO_CUSTOMERS_TABLE', 'sentra-demo-customers')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    # Build scan parameters
    scan_params = {}

    # Apply limit (default 100, max 1000)
    limit = filters.get('limit', 100)
    limit = min(limit, 1000)  # Enforce max limit
    scan_params['Limit'] = limit

    # Build filter expression
    filter_expressions = []

    if 'state' in filters:
        filter_expressions.append(Attr('state').eq(filters['state']))

    if 'name_contains' in filters:
        filter_expressions.append(Attr('name').contains(filters['name_contains']))

    if 'email_contains' in filters:
        filter_expressions.append(Attr('email').contains(filters['email_contains']))

    # Combine filter expressions
    if filter_expressions:
        combined_filter = filter_expressions[0]
        for expr in filter_expressions[1:]:
            combined_filter = combined_filter & expr
        scan_params['FilterExpression'] = combined_filter

    logger.info(
        "Tool initiated: query_customers",
        extra={
            "tool": "query_customers",
            "table": table_name,
            "filters": filters,
            "limit": limit
        }
    )

    # Execute scan
    response = table.scan(**scan_params)
    items = response.get('Items', [])

    # Remove SSN from results (PII protection)
    # Note: Security Controller may also block if SSN is detected
    for item in items:
        if 'ssn' in item:
            # Mask SSN for security
            item['ssn'] = 'XXX-XX-XXXX'

    # Log response preview (first 10 customers)
    preview_items = items[:10]
    logger.info(
        "Tool response: query_customers",
        extra={
            "tool": "query_customers",
            "count": len(items),
            "preview_count": len(preview_items),
            "preview": [{"customer_id": c.get("customer_id"), "name": c.get("name"), "state": c.get("state")} for c in preview_items]
        }
    )

    logger.info(
        "Tool completed: query_customers",
        extra={
            "tool": "query_customers",
            "table": table_name,
            "count": len(items)
        }
    )

    return items
