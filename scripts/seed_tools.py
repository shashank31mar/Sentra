#!/usr/bin/env python3
"""
Sentra MVP - Tool Registry Seed Script

Seeds sentra-tool-registry DynamoDB table with tool definitions.

Tool Types:
- READ tools: query_customers, query_orders, check_order, etc.
- WRITE tools: process_refund, reverse_refund, update_customer, etc.

Requirements:
    pip install boto3

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    # Run the script
    python scripts/seed_tools.py

    # Dry run (preview without writing)
    python scripts/seed_tools.py --dry-run

    # Force overwrite existing items
    python scripts/seed_tools.py --force

Reference: LLD 06 Section 2.2, 3.2 (Tool Registry)
"""

import argparse
import boto3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any


# AWS Configuration
AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"
TABLE_NAME = "sentra-tool-registry"


def get_timestamp() -> str:
    """Generate ISO 8601 timestamp with Z suffix"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")



def get_tool_data() -> List[Dict[str, Any]]:
    """
    Generate tool registry data

    Schema (per LLD 06 Section 2.2):
    - tool_id (STRING) - Primary Key
    - name (STRING)
    - description (STRING)
    - tool_type (STRING) - "READ" | "WRITE"
    - category (STRING) - "customer" | "order" | "payment" | "system"
    - status (STRING) - "active" | "deprecated" | "experimental"
    - version (STRING)
    - parameters (MAP) - Parameter definitions with validation
    - rate_limit (MAP) - Rate limiting configuration
    - execution_config (MAP) - Execution settings
    - created_at (STRING) - ISO 8601 timestamp
    - created_by (STRING)
    - tags (LIST of STRING)

    Returns:
        List of tool dictionaries
    """
    timestamp = get_timestamp()

    tools = [
        # READ TOOLS - Customer Category
        {
            "tool_id": "query_customers",
            "name": "Query Customers",
            "description": "Search and retrieve customer records with flexible filtering by name, email, state, or account status.",
            "tool_type": "READ",
            "category": "customer",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "name": {
                    "type": "string",
                    "required": False,
                    "description": "Customer name (partial match supported)",
                },
                "email": {
                    "type": "string",
                    "required": False,
                    "description": "Customer email address",
                },
                "state": {
                    "type": "string",
                    "required": False,
                    "description": "US state code (e.g., CA, NY)",
                    "pattern": "^[A-Z]{2}$",
                },
                "account_status": {
                    "type": "string",
                    "required": False,
                    "description": "Account status filter",
                    "enum": ["active", "inactive", "suspended"],
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "description": "Maximum number of results",
                    "default": 100,
                    "min": 1,
                    "max": 1000,
                },
            },
            "rate_limit": {"requests_per_minute": 100, "burst_limit": 20},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "customer", "query"],
        },
        {
            "tool_id": "get_customer_by_id",
            "name": "Get Customer By ID",
            "description": "Retrieve a single customer record by customer ID.",
            "tool_type": "READ",
            "category": "customer",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique customer identifier",
                    "pattern": "^cust-[a-f0-9]{8}$",
                }
            },
            "rate_limit": {"requests_per_minute": 200, "burst_limit": 50},
            "execution_config": {
                "timeout_seconds": 10,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "customer", "lookup"],
        },
        {
            "tool_id": "check_customer_status",
            "name": "Check Customer Status",
            "description": "Check if a customer account is active and in good standing.",
            "tool_type": "READ",
            "category": "customer",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique customer identifier",
                    "pattern": "^cust-[a-f0-9]{8}$",
                }
            },
            "rate_limit": {"requests_per_minute": 200, "burst_limit": 50},
            "execution_config": {
                "timeout_seconds": 10,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "customer", "validation"],
        },
        # READ TOOLS - Order Category
        {
            "tool_id": "query_orders",
            "name": "Query Orders",
            "description": "Search and retrieve order records with filtering by customer, status, date range, or amount.",
            "tool_type": "READ",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": False,
                    "description": "Filter by customer ID",
                    "pattern": "^cust-[a-f0-9]{8}$",
                },
                "status": {
                    "type": "string",
                    "required": False,
                    "description": "Order status filter",
                    "enum": ["completed", "shipped", "processing", "delivered", "cancelled"],
                },
                "min_amount": {
                    "type": "number",
                    "required": False,
                    "description": "Minimum order amount",
                    "min": 0,
                },
                "max_amount": {
                    "type": "number",
                    "required": False,
                    "description": "Maximum order amount",
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "description": "Maximum number of results",
                    "default": 100,
                    "min": 1,
                    "max": 1000,
                },
            },
            "rate_limit": {"requests_per_minute": 100, "burst_limit": 20},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "order", "query"],
        },
        {
            "tool_id": "get_order_by_id",
            "name": "Get Order By ID",
            "description": "Retrieve a single order record by order ID with full details.",
            "tool_type": "READ",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique order identifier",
                    "pattern": "^ord-[a-f0-9]{8}$",
                }
            },
            "rate_limit": {"requests_per_minute": 200, "burst_limit": 50},
            "execution_config": {
                "timeout_seconds": 10,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "order", "lookup"],
        },
        {
            "tool_id": "check_order",
            "name": "Check Order",
            "description": "Verify order exists and check its current status and eligibility for operations.",
            "tool_type": "READ",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique order identifier",
                    "pattern": "^ord-[a-f0-9]{8}$",
                }
            },
            "rate_limit": {"requests_per_minute": 200, "burst_limit": 50},
            "execution_config": {
                "timeout_seconds": 10,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "order", "validation"],
        },
        {
            "tool_id": "query_with_limit",
            "name": "Query With Limit",
            "description": "Generic query tool with strict result limits for safe exploration.",
            "tool_type": "READ",
            "category": "system",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "table": {
                    "type": "string",
                    "required": True,
                    "description": "Table to query",
                    "enum": ["customers", "orders"],
                },
                "filter": {
                    "type": "object",
                    "required": False,
                    "description": "Filter conditions",
                },
                "limit": {
                    "type": "integer",
                    "required": True,
                    "description": "Maximum number of results",
                    "min": 1,
                    "max": 100,
                },
            },
            "rate_limit": {"requests_per_minute": 50, "burst_limit": 10},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 2,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "system", "generic"],
        },
        {
            "tool_id": "get_customer_orders",
            "name": "Get Customer Orders",
            "description": "Retrieve all orders for a specific customer.",
            "tool_type": "READ",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique customer identifier",
                    "pattern": "^cust-[a-f0-9]{8}$",
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "description": "Maximum number of results",
                    "default": 50,
                    "min": 1,
                    "max": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 100, "burst_limit": 20},
            "execution_config": {
                "timeout_seconds": 20,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "order", "customer"],
        },
        {
            "tool_id": "search_orders_by_amount",
            "name": "Search Orders By Amount",
            "description": "Find orders within a specific amount range.",
            "tool_type": "READ",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "min_amount": {
                    "type": "number",
                    "required": True,
                    "description": "Minimum order amount",
                    "min": 0,
                },
                "max_amount": {
                    "type": "number",
                    "required": True,
                    "description": "Maximum order amount",
                    "min": 0,
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "description": "Maximum number of results",
                    "default": 100,
                    "min": 1,
                    "max": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 50, "burst_limit": 10},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "order", "search"],
        },
        {
            "tool_id": "get_order_history",
            "name": "Get Order History",
            "description": "Retrieve order history with status changes and timestamps.",
            "tool_type": "READ",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique order identifier",
                    "pattern": "^ord-[a-f0-9]{8}$",
                }
            },
            "rate_limit": {"requests_per_minute": 100, "burst_limit": 20},
            "execution_config": {
                "timeout_seconds": 15,
                "retry_attempts": 3,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read", "order", "history"],
        },
        # WRITE TOOLS - Payment Category
        {
            "tool_id": "process_refund",
            "name": "Process Refund",
            "description": "Process a refund for an order. Requires policy approval for amounts over threshold.",
            "tool_type": "WRITE",
            "category": "payment",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Order ID to refund",
                    "pattern": "^ord-[a-f0-9]{8}$",
                },
                "amount": {
                    "type": "number",
                    "required": True,
                    "description": "Refund amount in USD",
                    "min": Decimal("0.01"),
                    "max": 50000,
                },
                "reason": {
                    "type": "string",
                    "required": True,
                    "description": "Reason for refund",
                    "enum": [
                        "customer_request",
                        "damaged_product",
                        "wrong_item",
                        "late_delivery",
                        "other",
                    ],
                },
                "notes": {
                    "type": "string",
                    "required": False,
                    "description": "Additional notes",
                    "max_length": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 10, "burst_limit": 2},
            "execution_config": {
                "timeout_seconds": 60,
                "retry_attempts": 1,
                "idempotent": False,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "payment", "refund", "high-risk"],
        },
        {
            "tool_id": "reverse_refund",
            "name": "Reverse Refund",
            "description": "Reverse a previously processed refund. High-risk operation requiring approval.",
            "tool_type": "WRITE",
            "category": "payment",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "refund_id": {
                    "type": "string",
                    "required": True,
                    "description": "Refund transaction ID to reverse",
                    "pattern": "^ref-[a-f0-9]{8}$",
                },
                "reason": {
                    "type": "string",
                    "required": True,
                    "description": "Reason for reversal",
                    "enum": ["fraud", "error", "customer_request", "other"],
                },
                "notes": {
                    "type": "string",
                    "required": False,
                    "description": "Additional notes",
                    "max_length": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 5, "burst_limit": 1},
            "execution_config": {
                "timeout_seconds": 60,
                "retry_attempts": 1,
                "idempotent": False,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "payment", "refund", "high-risk", "reversal"],
        },
        {
            "tool_id": "partial_refund",
            "name": "Partial Refund",
            "description": "Process a partial refund for specific items in an order.",
            "tool_type": "WRITE",
            "category": "payment",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Order ID to refund",
                    "pattern": "^ord-[a-f0-9]{8}$",
                },
                "amount": {
                    "type": "number",
                    "required": True,
                    "description": "Partial refund amount in USD",
                    "min": Decimal("0.01"),
                    "max": 50000,
                },
                "items": {
                    "type": "array",
                    "required": True,
                    "description": "List of items to refund",
                },
                "reason": {
                    "type": "string",
                    "required": True,
                    "description": "Reason for partial refund",
                },
            },
            "rate_limit": {"requests_per_minute": 10, "burst_limit": 2},
            "execution_config": {
                "timeout_seconds": 60,
                "retry_attempts": 1,
                "idempotent": False,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "payment", "refund", "partial"],
        },
        # WRITE TOOLS - Customer Category
        {
            "tool_id": "update_customer",
            "name": "Update Customer",
            "description": "Update customer information (email, phone, address).",
            "tool_type": "WRITE",
            "category": "customer",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique customer identifier",
                    "pattern": "^cust-[a-f0-9]{8}$",
                },
                "email": {
                    "type": "string",
                    "required": False,
                    "description": "New email address",
                    "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
                },
                "phone": {
                    "type": "string",
                    "required": False,
                    "description": "New phone number",
                },
                "address": {
                    "type": "object",
                    "required": False,
                    "description": "New address",
                },
            },
            "rate_limit": {"requests_per_minute": 20, "burst_limit": 5},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 2,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "customer", "update"],
        },
        {
            "tool_id": "suspend_customer",
            "name": "Suspend Customer",
            "description": "Suspend a customer account. Requires approval and reason.",
            "tool_type": "WRITE",
            "category": "customer",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique customer identifier",
                    "pattern": "^cust-[a-f0-9]{8}$",
                },
                "reason": {
                    "type": "string",
                    "required": True,
                    "description": "Reason for suspension",
                    "enum": ["fraud", "abuse", "payment_issues", "other"],
                },
                "notes": {
                    "type": "string",
                    "required": False,
                    "description": "Additional notes",
                    "max_length": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 5, "burst_limit": 1},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 1,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "customer", "suspend", "high-risk"],
        },
        {
            "tool_id": "reactivate_customer",
            "name": "Reactivate Customer",
            "description": "Reactivate a suspended or inactive customer account.",
            "tool_type": "WRITE",
            "category": "customer",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "customer_id": {
                    "type": "string",
                    "required": True,
                    "description": "Unique customer identifier",
                    "pattern": "^cust-[a-f0-9]{8}$",
                },
                "notes": {
                    "type": "string",
                    "required": False,
                    "description": "Reactivation notes",
                    "max_length": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 10, "burst_limit": 2},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 2,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "customer", "reactivate"],
        },
        # WRITE TOOLS - Order Category
        {
            "tool_id": "cancel_order",
            "name": "Cancel Order",
            "description": "Cancel an order that is in processing or shipped status.",
            "tool_type": "WRITE",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Order ID to cancel",
                    "pattern": "^ord-[a-f0-9]{8}$",
                },
                "reason": {
                    "type": "string",
                    "required": True,
                    "description": "Cancellation reason",
                    "enum": [
                        "customer_request",
                        "out_of_stock",
                        "fraud",
                        "duplicate",
                        "other",
                    ],
                },
                "notes": {
                    "type": "string",
                    "required": False,
                    "description": "Additional notes",
                    "max_length": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 20, "burst_limit": 5},
            "execution_config": {
                "timeout_seconds": 45,
                "retry_attempts": 2,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "order", "cancel"],
        },
        {
            "tool_id": "update_order_status",
            "name": "Update Order Status",
            "description": "Update the status of an order (e.g., shipped, delivered).",
            "tool_type": "WRITE",
            "category": "order",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "order_id": {
                    "type": "string",
                    "required": True,
                    "description": "Order ID to update",
                    "pattern": "^ord-[a-f0-9]{8}$",
                },
                "new_status": {
                    "type": "string",
                    "required": True,
                    "description": "New order status",
                    "enum": ["processing", "shipped", "delivered", "cancelled"],
                },
                "notes": {
                    "type": "string",
                    "required": False,
                    "description": "Status update notes",
                    "max_length": 500,
                },
            },
            "rate_limit": {"requests_per_minute": 30, "burst_limit": 10},
            "execution_config": {
                "timeout_seconds": 30,
                "retry_attempts": 2,
                "idempotent": True,
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write", "order", "status"],
        },
    ]

    return tools



def seed_tools(dry_run: bool = False, force: bool = False) -> bool:
    """
    Seed tool registry table with tool data

    Args:
        dry_run: If True, preview changes without writing
        force: If True, overwrite existing items

    Returns:
        True if successful, False otherwise
    """
    print("=" * 80)
    print("Sentra MVP - Tool Registry Seed Script")
    print("=" * 80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No data will be written\n")

    # Get tool data
    tools = get_tool_data()
    read_tools = [t for t in tools if t["tool_type"] == "READ"]
    write_tools = [t for t in tools if t["tool_type"] == "WRITE"]

    print(f"\nGenerated {len(tools)} tools:")
    print(f"  - READ tools: {len(read_tools)}")
    print(f"  - WRITE tools: {len(write_tools)}")

    if dry_run:
        print("\n" + "=" * 80)
        print("Preview of Tool Data")
        print("=" * 80)

        print("\nREAD TOOLS:")
        for tool in read_tools:
            print(f"  - {tool['tool_id']} ({tool['category']}) - {tool['status']}")

        print("\nWRITE TOOLS:")
        for tool in write_tools:
            print(f"  - {tool['tool_id']} ({tool['category']}) - {tool['status']}")

        print("\n" + "=" * 80)
        print("Sample Tool Details")
        print("=" * 80)
        sample_tool = tools[0]
        print(f"\nTool: {sample_tool['name']}")
        print(f"  ID: {sample_tool['tool_id']}")
        print(f"  Type: {sample_tool['tool_type']}")
        print(f"  Category: {sample_tool['category']}")
        print(f"  Status: {sample_tool['status']}")
        print(f"  Parameters: {len(sample_tool['parameters'])} defined")
        print(f"  Rate Limit: {sample_tool['rate_limit']['requests_per_minute']} req/min")
        print(f"  Timeout: {sample_tool['execution_config']['timeout_seconds']}s")

        print("\n" + "=" * 80)
        print("✅ Dry run complete - no data written")
        print("=" * 80)
        return True

    # Set up boto3 session
    print(f"\nConnecting to AWS (profile: {AWS_PROFILE}, region: {AWS_REGION})...")
    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        dynamodb = session.resource("dynamodb")
        table = dynamodb.Table(TABLE_NAME)

        # Verify table exists
        table.table_status
        print(f"  ✅ Connected to table: {TABLE_NAME}")
    except Exception as e:
        print(f"  ❌ Error: Could not connect to table {TABLE_NAME}")
        print(f"  Error details: {e}")
        print(f"\n  Make sure:")
        print(f"    1. Storage Stack is deployed")
        print(f"    2. AWS credentials are configured")
        print(f"    3. Table name is correct")
        return False

    # Write tools to DynamoDB
    print(f"\n" + "=" * 80)
    print("Writing Tools to DynamoDB")
    print("=" * 80)

    written_count = 0
    skipped_count = 0
    error_count = 0

    for tool in tools:
        tool_id = tool["tool_id"]

        try:
            # Check if item exists (unless force mode)
            if not force:
                response = table.get_item(Key={"tool_id": tool_id})
                if "Item" in response:
                    print(
                        f"  ⚠️  Skipping {tool_id} - already exists (use --force to overwrite)"
                    )
                    skipped_count += 1
                    continue

            # Write item
            table.put_item(Item=tool)
            print(f"  ✅ Written: {tool_id} ({tool['tool_type']})")
            written_count += 1

        except Exception as e:
            print(f"  ❌ Error writing {tool_id}: {e}")
            error_count += 1

    # Summary
    print(f"\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"  Written: {written_count} tools")
    print(f"  Skipped: {skipped_count} tools")
    print(f"  Errors: {error_count} tools")

    if error_count > 0:
        print(f"\n  ⚠️  Some tools failed to write")
        return False
    elif written_count == 0 and skipped_count > 0:
        print(f"\n  ℹ️  All tools already exist - use --force to overwrite")
        return True
    else:
        print(f"\n  ✅ Successfully seeded {written_count} tools")
        return True



def verify_tools() -> bool:
    """
    Verify tools were written successfully

    Returns:
        True if verification passed, False otherwise
    """
    print(f"\n" + "=" * 80)
    print("Verification")
    print("=" * 80)

    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        dynamodb = session.resource("dynamodb")
        table = dynamodb.Table(TABLE_NAME)

        # Scan table to get count
        response = table.scan(Select="COUNT")
        actual_count = response["Count"]
        expected_count = 18  # Total tools

        print(f"\nTool count:")
        print(f"  Expected: {expected_count} tools")
        print(f"  Actual: {actual_count} tools")

        if actual_count == expected_count:
            print(f"  ✅ Verification passed!")

            # Query READ tools using GSI
            print(f"\nQuerying READ tools using type-index GSI...")
            response = table.query(
                IndexName="type-index",
                KeyConditionExpression="tool_type = :tool_type",
                ExpressionAttributeValues={":tool_type": "READ"},
            )
            read_count = response["Count"]
            print(f"  READ tools: {read_count}")

            # Query WRITE tools using GSI
            print(f"\nQuerying WRITE tools using type-index GSI...")
            response = table.query(
                IndexName="type-index",
                KeyConditionExpression="tool_type = :tool_type",
                ExpressionAttributeValues={":tool_type": "WRITE"},
            )
            write_count = response["Count"]
            print(f"  WRITE tools: {write_count}")

            print(f"  ✅ GSI queries successful")

            return True
        else:
            print(f"  ⚠️  Warning: Count mismatch!")
            return False

    except Exception as e:
        print(f"  ❌ Verification failed: {e}")
        return False


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description="Seed sentra-tool-registry DynamoDB table with tool data"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to DynamoDB",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing items"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only run verification (skip seeding)",
    )

    args = parser.parse_args()

    # Run verification only
    if args.verify_only:
        success = verify_tools()
        sys.exit(0 if success else 1)

    # Run seeding
    success = seed_tools(dry_run=args.dry_run, force=args.force)

    if not success:
        sys.exit(1)

    # Run verification (unless dry run)
    if not args.dry_run:
        verify_tools()

    print(f"\n" + "=" * 80)
    print("🎉 Tool seeding complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
