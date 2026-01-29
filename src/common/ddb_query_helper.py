"""
DynamoDB Query Helper - Reusable database query utilities
Sentra MVP - Workstream 9 - Milestone 1

This module provides production-grade DynamoDB query helpers with:
- Retry logic with exponential backoff
- Error handling and logging
- Result pagination
- Connection pooling

Reference: LLD 09 Section 4.2
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class DynamoDBQueryHelper:
    """
    Production-grade DynamoDB query helper with retry logic and error handling.

    Features:
    - Automatic retry with exponential backoff
    - Connection pooling
    - Result pagination
    - Decimal to float conversion
    """

    def __init__(
        self,
        region_name: Optional[str] = None,
        max_retries: int = 3,
        initial_retry_delay: float = 0.5
    ):
        """
        Initialize DynamoDB Query Helper.

        Args:
            region_name: AWS region (defaults to environment variable or us-east-1)
            max_retries: Maximum number of retry attempts
            initial_retry_delay: Initial retry delay in seconds (doubles each retry)
        """
        self.region_name = region_name or os.environ.get('AWS_REGION', 'us-east-1')
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay

        # Initialize DynamoDB resource (connection pooling)
        try:
            self.dynamodb = boto3.resource('dynamodb', region_name=self.region_name)
            logger.info(f"DynamoDB helper initialized for region: {self.region_name}")
        except Exception as e:
            logger.error(f"Failed to initialize DynamoDB resource: {e}")
            raise

    def query_with_retry(
        self,
        table_name: str,
        query_fn: callable,
        max_retries: Optional[int] = None
    ) -> Any:
        """
        Execute DynamoDB operation with retry logic.

        Args:
            table_name: DynamoDB table name
            query_fn: Function to execute (receives table object)
            max_retries: Override default max retries

        Returns:
            Query result

        Raises:
            ClientError: If all retries fail
        """
        max_retries = max_retries or self.max_retries
        retry_delay = self.initial_retry_delay

        for attempt in range(max_retries + 1):
            try:
                table = self.dynamodb.Table(table_name)
                result = query_fn(table)
                return result

            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')

                # Retryable errors
                if error_code in ['ProvisionedThroughputExceededException', 'ThrottlingException']:
                    if attempt < max_retries:
                        logger.warning(
                            f"DynamoDB throttled (attempt {attempt + 1}/{max_retries + 1}), retrying...",
                            extra={
                                "table": table_name,
                                "error_code": error_code,
                                "retry_delay": retry_delay
                            }
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue

                # Non-retryable errors or max retries reached
                logger.error(
                    f"DynamoDB query failed: {error_code}",
                    extra={
                        "table": table_name,
                        "error": str(e),
                        "attempt": attempt + 1
                    }
                )
                raise

            except Exception as e:
                logger.error(
                    f"Unexpected error during DynamoDB query: {e}",
                    extra={"table": table_name}
                )
                raise

    def get_item(
        self,
        table_name: str,
        key: Dict[str, Any],
        consistent_read: bool = False
    ) -> Optional[Dict]:
        """
        Get single item by primary key.

        Args:
            table_name: DynamoDB table name
            key: Primary key (e.g., {'customer_id': 'cust-123'})
            consistent_read: Use strongly consistent read

        Returns:
            Item dict or None if not found
        """
        def _get_item(table):
            response = table.get_item(
                Key=key,
                ConsistentRead=consistent_read
            )
            return response.get('Item')

        result = self.query_with_retry(table_name, _get_item)
        return self._convert_decimals(result) if result else None

    def query_by_index(
        self,
        table_name: str,
        index_name: str,
        key_condition: str,
        key_values: Dict[str, Any],
        filter_expression: Optional[Any] = None,
        limit: Optional[int] = None,
        scan_forward: bool = True
    ) -> List[Dict]:
        """
        Query items using Global Secondary Index (GSI).

        Args:
            table_name: DynamoDB table name
            index_name: GSI name
            key_condition: Key condition (e.g., 'state = :state')
            key_values: Expression attribute values (e.g., {':state': 'CA'})
            filter_expression: Optional filter expression
            limit: Maximum items to return
            scan_forward: True for ascending, False for descending

        Returns:
            List of items
        """
        def _query(table):
            query_params = {
                'IndexName': index_name,
                'KeyConditionExpression': key_condition,
                'ExpressionAttributeValues': key_values,
                'ScanIndexForward': scan_forward
            }

            if filter_expression:
                query_params['FilterExpression'] = filter_expression

            if limit:
                query_params['Limit'] = limit

            response = table.query(**query_params)
            return response.get('Items', [])

        items = self.query_with_retry(table_name, _query)
        return [self._convert_decimals(item) for item in items]

    def scan_with_filter(
        self,
        table_name: str,
        filter_expression: Optional[Any] = None,
        limit: Optional[int] = None,
        max_items: int = 1000
    ) -> List[Dict]:
        """
        Scan table with optional filter.

        WARNING: Scans are expensive. Use queries with indexes when possible.

        Args:
            table_name: DynamoDB table name
            filter_expression: Optional filter expression
            limit: Items per page
            max_items: Maximum total items to return

        Returns:
            List of items (up to max_items)
        """
        def _scan(table):
            scan_params = {}

            if filter_expression:
                scan_params['FilterExpression'] = filter_expression

            if limit:
                scan_params['Limit'] = limit

            items = []
            response = table.scan(**scan_params)
            items.extend(response.get('Items', []))

            # Pagination
            while 'LastEvaluatedKey' in response and len(items) < max_items:
                scan_params['ExclusiveStartKey'] = response['LastEvaluatedKey']
                response = table.scan(**scan_params)
                items.extend(response.get('Items', []))

            return items[:max_items]

        items = self.query_with_retry(table_name, _scan)
        return [self._convert_decimals(item) for item in items]

    def batch_get_items(
        self,
        table_name: str,
        keys: List[Dict[str, Any]]
    ) -> List[Dict]:
        """
        Get multiple items by primary keys (batch operation).

        Args:
            table_name: DynamoDB table name
            keys: List of primary keys

        Returns:
            List of items (may be less than keys if some not found)
        """
        if not keys:
            return []

        # DynamoDB batch_get_item limit is 100 items
        batch_size = 100
        all_items = []

        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i:i + batch_size]

            def _batch_get(table):
                response = self.dynamodb.batch_get_item(
                    RequestItems={
                        table_name: {
                            'Keys': batch_keys
                        }
                    }
                )
                return response.get('Responses', {}).get(table_name, [])

            items = self.query_with_retry(table_name, _batch_get)
            all_items.extend(items)

        return [self._convert_decimals(item) for item in all_items]

    def _convert_decimals(self, obj: Any) -> Any:
        """
        Convert DynamoDB Decimal types to float/int for JSON serialization.

        Args:
            obj: Object to convert (dict, list, or primitive)

        Returns:
            Converted object
        """
        if isinstance(obj, list):
            return [self._convert_decimals(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: self._convert_decimals(value) for key, value in obj.items()}
        elif isinstance(obj, Decimal):
            # Convert to int if no decimal places, otherwise float
            return int(obj) if obj % 1 == 0 else float(obj)
        else:
            return obj


# ==================== Module-level Helper Functions ====================

# Global helper instance (lazy-initialized)
_global_helper: Optional[DynamoDBQueryHelper] = None


def get_ddb_helper() -> DynamoDBQueryHelper:
    """
    Get global DynamoDB helper instance (singleton pattern).

    Returns:
        DynamoDBQueryHelper instance
    """
    global _global_helper
    if _global_helper is None:
        _global_helper = DynamoDBQueryHelper()
    return _global_helper


def query_customers_by_state(
    table_name: str,
    state: str,
    limit: int = 100
) -> List[Dict]:
    """
    Convenience function: Query customers by state.

    Args:
        table_name: Customers table name
        state: State code (e.g., 'CA', 'NY')
        limit: Maximum results

    Returns:
        List of customer records
    """
    helper = get_ddb_helper()
    return helper.query_by_index(
        table_name=table_name,
        index_name='state-index',
        key_condition='#state = :state',
        key_values={':state': state},
        limit=limit
    )


def query_orders_by_customer(
    table_name: str,
    customer_id: str,
    limit: int = 100
) -> List[Dict]:
    """
    Convenience function: Query orders by customer.

    Args:
        table_name: Orders table name
        customer_id: Customer ID
        limit: Maximum results

    Returns:
        List of order records
    """
    helper = get_ddb_helper()
    return helper.query_by_index(
        table_name=table_name,
        index_name='customer-index',
        key_condition='customer_id = :cid',
        key_values={':cid': customer_id},
        limit=limit
    )
