"""
Order ID Resolver - Fetches real order IDs from DynamoDB
Sentra MVP - Bug 002 Fix

Replaces hardcoded order IDs in scenario prompts with real order IDs
from the sentra-demo-orders table.
"""

import os
import re
import logging
import random
import time
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Pattern to match order ID placeholders (ORD-12345, ORD-56789, etc.)
ORDER_ID_PATTERN = re.compile(r'\bORD-\d+\b')

# Cache TTL in seconds
CACHE_TTL = 300


class OrderResolver:
    """Resolves placeholder order IDs to real DynamoDB order IDs"""
    
    def __init__(self):
        self.table_name = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
        self.region = os.environ.get('AWS_REGION', 'us-east-1')
        self._order_cache: List[Dict] = []
        self._cache_time: float = 0
    
    def _get_dynamodb_table(self):
        """Get DynamoDB table resource"""
        dynamodb = boto3.resource('dynamodb', region_name=self.region)
        return dynamodb.Table(self.table_name)
    
    def _refresh_cache(self) -> List[Dict]:
        """Fetch completed orders from DynamoDB"""
        current_time = time.time()
        if self._order_cache and (current_time - self._cache_time) < CACHE_TTL:
            return self._order_cache
        
        try:
            table = self._get_dynamodb_table()
            
            # Scan for completed orders (status=completed, no refund)
            response = table.scan(
                FilterExpression='#status = :completed AND attribute_not_exists(refund_status)',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':completed': 'completed'},
                Limit=100
            )
            
            orders = response.get('Items', [])
            
            if orders:
                self._order_cache = orders
                self._cache_time = current_time
                logger.info(f"Cached {len(orders)} available orders for demo scenarios")
            else:
                logger.warning("No completed orders found in DynamoDB")
            
            return self._order_cache
            
        except ClientError as e:
            logger.error(f"Failed to fetch orders from DynamoDB: {e}")
            return self._order_cache
    
    def resolve_prompt(self, prompt_text: str) -> str:
        """
        Replace placeholder order IDs with real order IDs
        
        Args:
            prompt_text: Original prompt with placeholders like ORD-12345
        
        Returns:
            Prompt with real order IDs substituted
        """
        placeholders = ORDER_ID_PATTERN.findall(prompt_text)
        
        if not placeholders:
            return prompt_text
        
        orders = self._refresh_cache()
        if not orders:
            logger.warning("No orders available, keeping placeholder IDs")
            return prompt_text
        
        resolved_text = prompt_text
        used_orders = set()
        
        for placeholder in placeholders:
            available = [o for o in orders if o['order_id'] not in used_orders]
            if not available:
                available = orders
            
            order = random.choice(available)
            real_order_id = order['order_id']
            used_orders.add(real_order_id)
            
            resolved_text = resolved_text.replace(placeholder, real_order_id, 1)
            logger.debug(f"Resolved {placeholder} -> {real_order_id}")
        
        return resolved_text


_resolver: Optional[OrderResolver] = None


def get_order_resolver() -> OrderResolver:
    """Get or create global resolver instance"""
    global _resolver
    if _resolver is None:
        _resolver = OrderResolver()
    return _resolver


def resolve_order_ids(prompt_text: str) -> str:
    """Convenience function to resolve order IDs in prompt text"""
    return get_order_resolver().resolve_prompt(prompt_text)
