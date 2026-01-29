"""
Tool: get_customer_by_id
Get single customer by ID from DynamoDB demo-customers table
"""

import os
import logging
from typing import Optional, Dict

import boto3

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def get_customer_by_id(customer_id: str) -> Optional[Dict]:
    """
    Get single customer by ID

    Args:
        customer_id: Customer identifier

    Returns:
        Customer record or None if not found

    Security Validations:
    - None (single record lookup is safe)
    """
    # Get environment configuration
    table_name = os.environ.get('DEMO_CUSTOMERS_TABLE', 'sentra-demo-customers')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    logger.info(
        "Tool initiated: get_customer_by_id",
        extra={
            "tool": "get_customer_by_id",
            "table": table_name,
            "customer_id": customer_id
        }
    )

    # Get item from DynamoDB
    response = table.get_item(Key={'customer_id': customer_id})
    item = response.get('Item')

    if item:
        # Mask SSN for security
        if 'ssn' in item:
            item['ssn'] = 'XXX-XX-XXXX'

        logger.info(
            "Tool response: get_customer_by_id",
            extra={
                "tool": "get_customer_by_id",
                "customer_id": customer_id,
                "customer_name": item.get("name"),
                "state": item.get("state")
            }
        )

        logger.info(
            "Tool completed: get_customer_by_id",
            extra={
                "tool": "get_customer_by_id",
                "table": table_name,
                "customer_id": customer_id,
                "found": True
            }
        )
    else:
        logger.info(
            "Tool completed: get_customer_by_id",
            extra={
                "tool": "get_customer_by_id",
                "table": table_name,
                "customer_id": customer_id,
                "found": False
            }
        )

    return item
