#!/usr/bin/env python3
"""
Sentra MVP - Demo Data Seeding Script

Seeds DynamoDB tables with realistic demo data:
- 500 orders (sentra-demo-orders)
- 500 customers (sentra-demo-customers)

Requirements:
    pip install boto3 faker

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1
    export AWS_ACCOUNT_ID=531109575379

    # Run the script
    python scripts/seed_demo_data.py

Reference: LLD 01 Section 3.3.3, 3.3.4 (Demo Data Tables)
"""

import boto3
import json
import random
import time
from datetime import datetime, timedelta
from decimal import Decimal
from faker import Faker
from typing import List, Dict, Any
import sys

# Initialize Faker with US locale
fake = Faker('en_US')

# AWS Configuration
AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"

# DynamoDB Table Names (from config)
ORDERS_TABLE = "sentra-demo-orders"
CUSTOMERS_TABLE = "sentra-demo-customers"

# Data Generation Settings
NUM_CUSTOMERS = 500
NUM_ORDERS = 500

# State Distribution (as per LLD requirements)
STATE_DISTRIBUTION = {
    'CA': 150,  # California
    'NY': 100,  # New York
    'TX': 80,   # Texas
    'FL': 70,   # Florida
    'IL': 20,   # Illinois
    'PA': 20,   # Pennsylvania
    'OH': 20,   # Ohio
    'NC': 10,   # North Carolina
    'GA': 10,   # Georgia
    'MI': 10,   # Michigan
    'VA': 10,   # Virginia
}

# Product catalog for orders
PRODUCTS = [
    {"name": "Laptop Pro 15", "category": "Electronics", "price_range": (1200, 2500)},
    {"name": "Wireless Headphones", "category": "Electronics", "price_range": (150, 400)},
    {"name": "Smart Watch Ultra", "category": "Electronics", "price_range": (300, 800)},
    {"name": "4K Monitor", "category": "Electronics", "price_range": (400, 1200)},
    {"name": "Mechanical Keyboard", "category": "Electronics", "price_range": (100, 300)},
    {"name": "Office Chair Pro", "category": "Furniture", "price_range": (250, 800)},
    {"name": "Standing Desk", "category": "Furniture", "price_range": (400, 1500)},
    {"name": "Coffee Maker Deluxe", "category": "Appliances", "price_range": (100, 500)},
    {"name": "Air Purifier", "category": "Appliances", "price_range": (150, 600)},
    {"name": "Smart Speaker", "category": "Electronics", "price_range": (50, 200)},
]

ORDER_STATUSES = ["completed"]  # All orders are completed for demo refund testing


def generate_fake_ssn() -> str:
    """
    Generate fake SSN for demo purposes (PII detection testing)
    Format: XXX-XX-XXXX
    Note: These are NOT real SSNs - generated for testing only
    """
    return f"{random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(1000, 9999)}"


def generate_customer_id() -> str:
    """Generate unique customer ID"""
    return f"cust-{fake.uuid4()[:8]}"


def generate_order_id() -> str:
    """Generate unique order ID"""
    return f"ord-{fake.uuid4()[:8]}"


def generate_customers(num_customers: int) -> List[Dict[str, Any]]:
    """
    Generate fake customer data

    Schema (per LLD Section 3.3.4):
    - customer_id (STRING) - Primary Key
    - name (STRING)
    - email (STRING)
    - ssn (STRING) - FAKE, for PII detection demo
    - phone (STRING)
    - state (STRING) - For state-index GSI
    - created_at (NUMBER) - For GSI sort key
    - account_status (STRING)

    Args:
        num_customers: Number of customers to generate

    Returns:
        List of customer dictionaries
    """
    customers = []
    states = []

    # Build state list based on distribution
    for state, count in STATE_DISTRIBUTION.items():
        states.extend([state] * count)

    # Generate customers
    for i in range(num_customers):
        # Calculate created_at timestamp (spread over last 2 years)
        created_days_ago = random.randint(0, 730)
        created_at = datetime.now() - timedelta(days=created_days_ago)

        customer = {
            "customer_id": generate_customer_id(),
            "name": fake.name(),
            "email": fake.email(),
            "ssn": generate_fake_ssn(),  # Fake SSN for PII detection testing
            "phone": fake.phone_number(),
            "state": states[i] if i < len(states) else random.choice(list(STATE_DISTRIBUTION.keys())),
            "created_at": int(created_at.timestamp()),
            "account_status": random.choice(["active", "active", "active", "inactive", "suspended"]),
            # Weight toward "active" status
        }
        customers.append(customer)

    return customers


def generate_orders(num_orders: int, customers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate fake order data

    Schema (per LLD Section 3.3.3):
    - order_id (STRING) - Primary Key
    - customer_id (STRING) - For customer-index GSI
    - customer_name (STRING)
    - amount (NUMBER) - $100 to $50,000 range
    - status (STRING)
    - order_date (STRING)
    - created_at (NUMBER) - For GSI sort key
    - items (LIST) - List of items in order
    - shipping_address (MAP)

    Args:
        num_orders: Number of orders to generate
        customers: List of customer dictionaries (to link orders to customers)

    Returns:
        List of order dictionaries
    """
    orders = []

    for _ in range(num_orders):
        # Pick random customer
        customer = random.choice(customers)

        # Calculate order date (spread over last year)
        order_days_ago = random.randint(0, 365)
        order_date = datetime.now() - timedelta(days=order_days_ago)

        # Generate 1-5 items per order
        num_items = random.randint(1, 5)
        items = []
        total_amount = 0

        for _ in range(num_items):
            product = random.choice(PRODUCTS)
            quantity = random.randint(1, 3)
            price = Decimal(str(round(random.uniform(*product["price_range"]), 2)))
            item_total = Decimal(str(round(float(price) * quantity, 2)))
            total_amount += item_total

            items.append({
                "product_name": product["name"],
                "category": product["category"],
                "quantity": quantity,
                "unit_price": price,
                "total": item_total,
            })

        # Ensure total_amount is Decimal
        total_amount = Decimal(str(round(float(total_amount), 2)))

        # Generate shipping address
        shipping_address = {
            "street": fake.street_address(),
            "city": fake.city(),
            "state": customer["state"],  # Use customer's state
            "zip_code": fake.zipcode(),
        }

        order = {
            "order_id": generate_order_id(),
            "customer_id": customer["customer_id"],
            "customer_name": customer["name"],
            "amount": total_amount,
            "status": random.choice(ORDER_STATUSES),
            "order_date": order_date.strftime("%Y-%m-%d"),
            "created_at": int(order_date.timestamp()),
            "items": items,
            "shipping_address": shipping_address,
        }
        orders.append(order)

    return orders


def batch_write_items(dynamodb, table_name: str, items: List[Dict[str, Any]], batch_size: int = 25):
    """
    Write items to DynamoDB in batches

    DynamoDB BatchWriteItem has a limit of 25 items per request

    Args:
        dynamodb: Boto3 DynamoDB resource
        table_name: Name of the table to write to
        items: List of items to write
        batch_size: Number of items per batch (max 25)
    """
    table = dynamodb.Table(table_name)
    total_items = len(items)
    written_count = 0

    print(f"Writing {total_items} items to {table_name} in batches of {batch_size}...")

    # Process in batches
    for i in range(0, total_items, batch_size):
        batch = items[i:i + batch_size]

        with table.batch_writer() as writer:
            for item in batch:
                writer.put_item(Item=item)
                written_count += 1

        # Progress indicator
        print(f"  Progress: {written_count}/{total_items} items written ({written_count * 100 // total_items}%)")

        # Small delay to avoid throttling
        time.sleep(0.1)

    print(f"✅ Successfully wrote {written_count} items to {table_name}")


def verify_data(dynamodb, table_name: str, expected_count: int):
    """
    Verify data was written successfully

    Args:
        dynamodb: Boto3 DynamoDB resource
        table_name: Name of the table to verify
        expected_count: Expected number of items
    """
    table = dynamodb.Table(table_name)

    # Scan table to get count (note: this is not efficient for large tables)
    response = table.scan(Select='COUNT')
    actual_count = response['Count']

    print(f"\nVerification for {table_name}:")
    print(f"  Expected: {expected_count} items")
    print(f"  Actual: {actual_count} items")

    if actual_count == expected_count:
        print(f"  ✅ Verification passed!")
    else:
        print(f"  ⚠️  Warning: Count mismatch!")

    return actual_count == expected_count


def main():
    """Main execution"""
    print("=" * 80)
    print("Sentra MVP - Demo Data Seeding Script")
    print("=" * 80)

    # Set up boto3 session with profile
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    dynamodb = session.resource('dynamodb')

    # Verify tables exist
    print(f"\nVerifying DynamoDB tables exist...")
    try:
        customers_table = dynamodb.Table(CUSTOMERS_TABLE)
        orders_table = dynamodb.Table(ORDERS_TABLE)

        # Trigger a describe to verify table exists
        customers_table.table_status
        orders_table.table_status

        print(f"  ✅ {CUSTOMERS_TABLE} table found")
        print(f"  ✅ {ORDERS_TABLE} table found")
    except Exception as e:
        print(f"  ❌ Error: Could not find tables. Make sure Storage Stack is deployed.")
        print(f"  Error details: {e}")
        sys.exit(1)

    # Generate data
    print(f"\n" + "=" * 80)
    print("Generating Demo Data")
    print("=" * 80)

    print(f"\n1. Generating {NUM_CUSTOMERS} customers...")
    customers = generate_customers(NUM_CUSTOMERS)
    print(f"   ✅ Generated {len(customers)} customers")
    print(f"   State distribution: {STATE_DISTRIBUTION}")

    print(f"\n2. Generating {NUM_ORDERS} orders...")
    orders = generate_orders(NUM_ORDERS, customers)
    print(f"   ✅ Generated {len(orders)} orders")
    print(f"   Amount range: ${float(min(o['amount'] for o in orders)):.2f} - ${float(max(o['amount'] for o in orders)):.2f}")

    # Write data to DynamoDB
    print(f"\n" + "=" * 80)
    print("Writing Data to DynamoDB")
    print("=" * 80)

    print(f"\n1. Writing customers to {CUSTOMERS_TABLE}...")
    batch_write_items(dynamodb, CUSTOMERS_TABLE, customers)

    print(f"\n2. Writing orders to {ORDERS_TABLE}...")
    batch_write_items(dynamodb, ORDERS_TABLE, orders)

    # Verify data
    print(f"\n" + "=" * 80)
    print("Verification")
    print("=" * 80)

    verify_data(dynamodb, CUSTOMERS_TABLE, NUM_CUSTOMERS)
    verify_data(dynamodb, ORDERS_TABLE, NUM_ORDERS)

    # Summary
    print(f"\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"✅ Successfully seeded demo data:")
    print(f"   - {NUM_CUSTOMERS} customers in {CUSTOMERS_TABLE}")
    print(f"   - {NUM_ORDERS} orders in {ORDERS_TABLE}")
    print(f"   - Total: {NUM_CUSTOMERS + NUM_ORDERS} items")
    print(f"\n📊 Sample customer (for testing):")

    sample_customer = customers[0]
    print(f"   Customer ID: {sample_customer['customer_id']}")
    print(f"   Name: {sample_customer['name']}")
    print(f"   Email: {sample_customer['email']}")
    print(f"   State: {sample_customer['state']}")
    print(f"   SSN (FAKE): {sample_customer['ssn']}")

    print(f"\n📦 Sample order (for testing):")
    sample_order = orders[0]
    print(f"   Order ID: {sample_order['order_id']}")
    print(f"   Customer: {sample_order['customer_name']}")
    print(f"   Amount: ${float(sample_order['amount']):.2f}")
    print(f"   Status: {sample_order['status']}")
    print(f"   Items: {len(sample_order['items'])} items")

    print(f"\n" + "=" * 80)
    print("🎉 Demo data seeding complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
