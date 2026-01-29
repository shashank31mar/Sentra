#!/usr/bin/env python3
"""
Sentra MVP - Large-Scale Demo Data Seeding Script

Seeds DynamoDB tables with 1 million+ records using multiprocessing.

Requirements:
    pip install boto3 faker

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    # Seed 1M customers
    python scripts/seed_demo_data_large.py --table sentra-customers --count 1000000

    # Seed 1M orders
    python scripts/seed_demo_data_large.py --table sentra-orders --count 1000000

    # Customize workers
    python scripts/seed_demo_data_large.py --table sentra-customers --count 100000 --workers 4

Reference: LLD 09 Appendix A.2 (Option A - Enhanced Batch Seed Script)
"""

import argparse
import multiprocessing as mp
from functools import partial
import boto3
from faker import Faker
import time
import random
import sys
import os
from datetime import datetime, timedelta
from decimal import Decimal


# AWS Configuration
AWS_PROFILE = os.getenv("AWS_PROFILE", "sentra")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# State distribution for customers (realistic US distribution)
STATE_DISTRIBUTION = ['CA', 'NY', 'TX', 'FL', 'IL', 'PA', 'OH', 'NC', 'GA', 'MI', 'VA']

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

ORDER_STATUSES = ["completed", "shipped", "processing", "delivered", "cancelled"]


def generate_customer_batch(batch_id, batch_size, table_name):
    """
    Generate and write one batch of customer records.

    Args:
        batch_id: Unique batch identifier
        batch_size: Number of records to generate
        table_name: DynamoDB table name

    Returns:
        Number of records written
    """
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(table_name)
    fake = Faker('en_US')

    items = []
    for i in range(batch_size):
        # Generate customer record
        state = random.choice(STATE_DISTRIBUTION)
        created_date = fake.date_time_between(start_date='-2y', end_date='now')

        item = {
            'customer_id': f'cust-{batch_id:06d}-{i:04d}',
            'name': fake.name(),
            'email': fake.email(),
            'state': state,
            'phone': fake.phone_number(),
            'address': {
                'street': fake.street_address(),
                'city': fake.city(),
                'zip': fake.zipcode()
            },
            'created_at': created_date.isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
        items.append(item)

    # Write batch (25 items max per DynamoDB batch)
    written = 0
    for chunk_start in range(0, len(items), 25):
        chunk = items[chunk_start:chunk_start + 25]
        try:
            with table.batch_writer() as batch:
                for item in chunk:
                    batch.put_item(Item=item)
            written += len(chunk)
        except Exception as e:
            print(f"Error writing batch {batch_id} chunk {chunk_start}: {e}", file=sys.stderr)

    return written


def generate_order_batch(batch_id, batch_size, table_name, customer_count):
    """
    Generate and write one batch of order records.

    Args:
        batch_id: Unique batch identifier
        batch_size: Number of records to generate
        table_name: DynamoDB table name
        customer_count: Total number of customers (for foreign key generation)

    Returns:
        Number of records written
    """
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(table_name)
    fake = Faker('en_US')

    items = []
    for i in range(batch_size):
        # Generate order record
        # Link to random customer (assumes customers already seeded)
        customer_batch = random.randint(0, customer_count // 1000 - 1)
        customer_idx = random.randint(0, 999)
        customer_id = f'cust-{customer_batch:06d}-{customer_idx:04d}'

        created_date = fake.date_time_between(start_date='-1y', end_date='now')
        status = random.choice(ORDER_STATUSES)

        # Generate 1-3 items per order
        num_items = random.randint(1, 3)
        order_items = []
        total_amount = Decimal(0)

        for _ in range(num_items):
            product = random.choice(PRODUCTS)
            quantity = random.randint(1, 3)
            price = Decimal(random.uniform(*product['price_range'])).quantize(Decimal('0.01'))
            item_total = price * quantity
            total_amount += item_total

            order_items.append({
                'name': product['name'],
                'category': product['category'],
                'quantity': quantity,
                'price': float(price),
                'total': float(item_total)
            })

        item = {
            'order_id': f'ORD-{batch_id:06d}-{i:04d}',
            'customer_id': customer_id,
            'amount': float(total_amount),
            'status': status,
            'items': order_items,
            'created_at': created_date.isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
        items.append(item)

    # Write batch (25 items max per DynamoDB batch)
    written = 0
    for chunk_start in range(0, len(items), 25):
        chunk = items[chunk_start:chunk_start + 25]
        try:
            with table.batch_writer() as batch:
                for item in chunk:
                    batch.put_item(Item=item)
            written += len(chunk)
        except Exception as e:
            print(f"Error writing batch {batch_id} chunk {chunk_start}: {e}", file=sys.stderr)

    return written


def seed_large_dataset(table_name, total_count, num_workers=8, table_type='customers'):
    """
    Seed large dataset using multiprocessing.

    Args:
        table_name: DynamoDB table name
        total_count: Total records to generate
        num_workers: Number of parallel workers
        table_type: 'customers' or 'orders'
    """
    batch_size = 1000  # Records per worker batch
    num_batches = total_count // batch_size

    print(f"\n{'='*60}")
    print(f"Seeding {total_count:,} {table_type} into {table_name}")
    print(f"Using {num_workers} workers, {num_batches} batches of {batch_size}")
    print(f"{'='*60}\n")

    start_time = time.time()

    # Create pool and map work
    if table_type == 'customers':
        worker_fn = partial(generate_customer_batch, batch_size=batch_size, table_name=table_name)
    elif table_type == 'orders':
        # For orders, need to know customer count for foreign keys
        worker_fn = partial(
            generate_order_batch,
            batch_size=batch_size,
            table_name=table_name,
            customer_count=total_count  # Assumes same count as orders for simplicity
        )
    else:
        raise ValueError(f"Unknown table_type: {table_type}")

    with mp.Pool(processes=num_workers) as pool:
        results = pool.map(worker_fn, range(num_batches))

    elapsed = time.time() - start_time
    total_written = sum(results)

    print(f"\n{'='*60}")
    print(f"✅ Seeded {total_written:,} records in {elapsed:.1f}s")
    print(f"   Rate: {total_written/elapsed:.0f} records/sec")
    print(f"{'='*60}\n")

    return total_written


def main():
    parser = argparse.ArgumentParser(
        description='Seed DynamoDB tables with large-scale demo data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Seed 1M customers
    python scripts/seed_demo_data_large.py --table sentra-customers --count 1000000

    # Seed 100K orders (faster)
    python scripts/seed_demo_data_large.py --table sentra-orders --count 100000 --workers 4

Note: For > 1M records, consider using S3 Import (see LLD 09 Appendix A.2 Option B)
        """
    )
    parser.add_argument('--table', type=str, required=True, help='DynamoDB table name')
    parser.add_argument('--count', type=int, default=100000, help='Total records to generate')
    parser.add_argument('--workers', type=int, default=8, help='Number of parallel workers')
    args = parser.parse_args()

    # Determine table type from table name
    if 'customer' in args.table.lower():
        table_type = 'customers'
    elif 'order' in args.table.lower():
        table_type = 'orders'
    else:
        print(f"Error: Cannot determine table type from table name: {args.table}")
        print("Table name should contain 'customer' or 'order'")
        sys.exit(1)

    # Validate count
    if args.count < 1000:
        print("Warning: For < 1000 records, use scripts/seed_demo_data.py instead")

    if args.count > 10000000:
        print("Warning: For > 10M records, use S3 Import (see LLD 09 Appendix A.2 Option B)")
        confirm = input("Continue anyway? (yes/no): ")
        if confirm.lower() != 'yes':
            sys.exit(0)

    # Run seeding
    total_written = seed_large_dataset(
        table_name=args.table,
        total_count=args.count,
        num_workers=args.workers,
        table_type=table_type
    )

    print(f"Seeding complete! {total_written:,} records written to {args.table}")


if __name__ == '__main__':
    main()
