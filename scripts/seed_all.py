#!/usr/bin/env python3
"""
Sentra MVP - Master Seed Script

Orchestrates all seed scripts to populate the data model v2 tables.

Seeds:
1. sentra-agent-registry (3 agents)
2. sentra-tool-registry (18 tools)
3. sentra-sigma-rules-metadata (11 Sigma rules)
4. sentra-policies-metadata (2 policies)

Requirements:
    pip install boto3 pyyaml

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    # Run all seed scripts
    python scripts/seed_all.py

    # Dry run (preview without writing)
    python scripts/seed_all.py --dry-run

    # Force overwrite existing items
    python scripts/seed_all.py --force

Reference: LLD 06 Section 3 (Data Model v2 Seeding)
"""

import argparse
import sys
from datetime import datetime, timezone

# Import individual seed functions
from seed_agents import seed_agents, verify_agents
from seed_tools import seed_tools, verify_tools
from seed_sigma_rules_metadata import (
    seed_sigma_rules_metadata,
    verify_sigma_rules_metadata,
)
from seed_policies_metadata import seed_policies_metadata, verify_policies_metadata


def print_banner(text: str, char: str = "="):
    """Print a formatted banner"""
    print(f"\n{char * 80}")
    print(text)
    print(f"{char * 80}\n")


def get_timestamp() -> str:
    """Generate ISO 8601 timestamp with Z suffix"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def seed_all_tables(dry_run: bool = False, force: bool = False) -> dict:
    """
    Seed all data model v2 tables

    Args:
        dry_run: If True, preview changes without writing
        force: If True, overwrite existing items

    Returns:
        Dictionary with results for each table
    """
    start_time = datetime.now(timezone.utc)

    print_banner("Sentra MVP - Master Seed Script", "=")
    print(f"Started at: {get_timestamp()}")

    if dry_run:
        print("⚠️  DRY RUN MODE - No data will be written")

    results = {
        "agents": {"success": False, "error": None},
        "tools": {"success": False, "error": None},
        "sigma_rules": {"success": False, "error": None},
        "policies": {"success": False, "error": None},
    }

    # ============================================================
    # Step 1: Seed Agent Registry
    # ============================================================
    print_banner("Step 1/4: Seeding Agent Registry", "-")
    try:
        success = seed_agents(dry_run=dry_run, force=force)
        results["agents"]["success"] = success
        if not success:
            print("⚠️  Agent seeding completed with warnings")
    except Exception as e:
        print(f"❌ Error seeding agents: {e}")
        results["agents"]["error"] = str(e)

    # ============================================================
    # Step 2: Seed Tool Registry
    # ============================================================
    print_banner("Step 2/4: Seeding Tool Registry", "-")
    try:
        success = seed_tools(dry_run=dry_run, force=force)
        results["tools"]["success"] = success
        if not success:
            print("⚠️  Tool seeding completed with warnings")
    except Exception as e:
        print(f"❌ Error seeding tools: {e}")
        results["tools"]["error"] = str(e)

    # ============================================================
    # Step 3: Seed Sigma Rules Metadata
    # ============================================================
    print_banner("Step 3/4: Seeding Sigma Rules Metadata", "-")
    try:
        success = seed_sigma_rules_metadata(dry_run=dry_run, force=force)
        results["sigma_rules"]["success"] = success
        if not success:
            print("⚠️  Sigma rules seeding completed with warnings")
    except Exception as e:
        print(f"❌ Error seeding Sigma rules: {e}")
        results["sigma_rules"]["error"] = str(e)

    # ============================================================
    # Step 4: Seed Policy Metadata
    # ============================================================
    print_banner("Step 4/4: Seeding Policy Metadata", "-")
    try:
        success = seed_policies_metadata(dry_run=dry_run, force=force)
        results["policies"]["success"] = success
        if not success:
            print("⚠️  Policy seeding completed with warnings")
    except Exception as e:
        print(f"❌ Error seeding policies: {e}")
        results["policies"]["error"] = str(e)

    # Calculate duration
    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    return results, duration



def verify_all_tables() -> dict:
    """
    Verify all tables were seeded successfully

    Returns:
        Dictionary with verification results for each table
    """
    print_banner("Verification - All Tables", "=")

    verification_results = {
        "agents": False,
        "tools": False,
        "sigma_rules": False,
        "policies": False,
    }

    # Verify agents
    print("\n" + "-" * 80)
    print("Verifying Agent Registry...")
    print("-" * 80)
    try:
        verification_results["agents"] = verify_agents()
    except Exception as e:
        print(f"❌ Agent verification failed: {e}")

    # Verify tools
    print("\n" + "-" * 80)
    print("Verifying Tool Registry...")
    print("-" * 80)
    try:
        verification_results["tools"] = verify_tools()
    except Exception as e:
        print(f"❌ Tool verification failed: {e}")

    # Verify Sigma rules
    print("\n" + "-" * 80)
    print("Verifying Sigma Rules Metadata...")
    print("-" * 80)
    try:
        verification_results["sigma_rules"] = verify_sigma_rules_metadata()
    except Exception as e:
        print(f"❌ Sigma rules verification failed: {e}")

    # Verify policies
    print("\n" + "-" * 80)
    print("Verifying Policy Metadata...")
    print("-" * 80)
    try:
        verification_results["policies"] = verify_policies_metadata()
    except Exception as e:
        print(f"❌ Policy verification failed: {e}")

    return verification_results


def print_summary(results: dict, verification_results: dict, duration: float, dry_run: bool):
    """Print final summary of seeding operation"""
    print_banner("Final Summary", "=")

    print(f"Duration: {duration:.2f} seconds\n")

    # Seeding results
    print("Seeding Results:")
    print("-" * 80)
    success_count = 0
    error_count = 0

    for table, result in results.items():
        status = "✅ SUCCESS" if result["success"] else "❌ FAILED"
        print(f"  {table.ljust(20)}: {status}")
        if result["error"]:
            print(f"    Error: {result['error']}")
        if result["success"]:
            success_count += 1
        else:
            error_count += 1

    # Verification results (if not dry run)
    if not dry_run:
        print("\nVerification Results:")
        print("-" * 80)
        verified_count = 0

        for table, verified in verification_results.items():
            status = "✅ VERIFIED" if verified else "❌ FAILED"
            print(f"  {table.ljust(20)}: {status}")
            if verified:
                verified_count += 1

        print(f"\nVerified: {verified_count}/{len(verification_results)} tables")

    # Overall status
    print("\n" + "=" * 80)
    if dry_run:
        print("🎉 Dry run complete - no data written")
    elif success_count == len(results) and (not verification_results or sum(verification_results.values()) == len(verification_results)):
        print("🎉 All tables seeded and verified successfully!")
    elif error_count == 0:
        print("✅ All tables seeded (some verification warnings)")
    else:
        print(f"⚠️  Seeding completed with {error_count} errors")

    print("=" * 80)


def seed_demo_data_large(customer_count: int = 1000000, order_count: int = 1000000, workers: int = 8):
    """
    Seed large-scale demo data (customers and orders).

    Args:
        customer_count: Number of customer records to generate
        order_count: Number of order records to generate
        workers: Number of parallel workers
    """
    import subprocess

    print_banner("Seeding Large-Scale Demo Data (Customers & Orders)", "=")
    print(f"Customer records: {customer_count:,}")
    print(f"Order records: {order_count:,}")
    print(f"Workers: {workers}\n")

    # Seed customers
    print_banner("Seeding Customers", "-")
    try:
        result = subprocess.run(
            [
                "python3", "scripts/seed_demo_data_large.py",
                "--table", "sentra-customers",
                "--count", str(customer_count),
                "--workers", str(workers)
            ],
            check=True,
            capture_output=False
        )
        print("✅ Customer seeding complete")
    except subprocess.CalledProcessError as e:
        print(f"❌ Customer seeding failed: {e}")
        return False

    # Seed orders
    print_banner("Seeding Orders", "-")
    try:
        result = subprocess.run(
            [
                "python3", "scripts/seed_demo_data_large.py",
                "--table", "sentra-orders",
                "--count", str(order_count),
                "--workers", str(workers)
            ],
            check=True,
            capture_output=False
        )
        print("✅ Order seeding complete")
    except subprocess.CalledProcessError as e:
        print(f"❌ Order seeding failed: {e}")
        return False

    return True


def count_items_in_tables(include_demo_data: bool = False):
    """
    Count items in all tables and display summary.

    Args:
        include_demo_data: If True, include demo data tables (customers, orders)
    """
    import boto3

    print_banner("Table Item Counts", "=")

    try:
        session = boto3.Session(profile_name="sentra", region_name="us-east-1")
        dynamodb = session.resource("dynamodb")

        tables = {
            "sentra-agent-registry": "Agents",
            "sentra-tool-registry": "Tools",
            "sentra-sigma-rules-metadata": "Sigma Rules",
            "sentra-policies-metadata": "Policies",
        }

        if include_demo_data:
            tables.update({
                "sentra-customers": "Demo Customers",
                "sentra-orders": "Demo Orders",
            })

        total_items = 0

        for table_name, display_name in tables.items():
            try:
                table = dynamodb.Table(table_name)
                response = table.scan(Select="COUNT")
                count = response["Count"]
                total_items += count
                print(f"  {display_name.ljust(20)}: {count:,} items")
            except Exception as e:
                print(f"  {display_name.ljust(20)}: Error - {e}")

        print(f"\n  {'Total'.ljust(20)}: {total_items:,} items")
        print("=" * 80)

    except Exception as e:
        print(f"❌ Error counting items: {e}")


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description="Master seed script - seeds all data model v2 tables",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Seed metadata tables only
    python scripts/seed_all.py

    # Seed metadata + 1M demo data (customers & orders)
    python scripts/seed_all.py --seed-demo-data

    # Seed demo data with custom counts
    python scripts/seed_all.py --seed-demo-data --customers 500000 --orders 500000

    # Count all items (including demo data)
    python scripts/seed_all.py --count-only --include-demo-data
        """
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
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Only count items in tables (skip seeding)",
    )
    parser.add_argument(
        "--seed-demo-data",
        action="store_true",
        help="Seed large-scale demo data (customers & orders) after metadata tables"
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=1000000,
        help="Number of customer records to generate (default: 1,000,000)"
    )
    parser.add_argument(
        "--orders",
        type=int,
        default=1000000,
        help="Number of order records to generate (default: 1,000,000)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers for demo data seeding (default: 8)"
    )
    parser.add_argument(
        "--include-demo-data",
        action="store_true",
        help="Include demo data tables in counts/verification"
    )

    args = parser.parse_args()

    # Count only mode
    if args.count_only:
        count_items_in_tables(include_demo_data=args.include_demo_data)
        sys.exit(0)

    # Verify only mode
    if args.verify_only:
        verification_results = verify_all_tables()
        verified_count = sum(verification_results.values())
        total_count = len(verification_results)

        print_banner("Verification Summary", "=")
        print(f"Verified: {verified_count}/{total_count} tables")

        if verified_count == total_count:
            print("✅ All tables verified successfully!")
            sys.exit(0)
        else:
            print("⚠️  Some tables failed verification")
            sys.exit(1)

    # Run seeding
    results, duration = seed_all_tables(dry_run=args.dry_run, force=args.force)

    # Run verification (unless dry run)
    verification_results = {}
    if not args.dry_run:
        verification_results = verify_all_tables()

    # Print summary
    print_summary(results, verification_results, duration, args.dry_run)

    # Seed demo data if requested
    demo_success = True
    if args.seed_demo_data and not args.dry_run:
        demo_success = seed_demo_data_large(
            customer_count=args.customers,
            order_count=args.orders,
            workers=args.workers
        )

        if demo_success:
            print_banner("Demo Data Seeding Complete", "=")
            print("✅ Large-scale demo data seeded successfully!")
            print(f"   Customers: {args.customers:,}")
            print(f"   Orders: {args.orders:,}")
            print("=" * 80)
        else:
            print_banner("Demo Data Seeding Failed", "=")
            print("❌ Large-scale demo data seeding encountered errors")
            print("=" * 80)

    # Exit with appropriate code
    error_count = sum(1 for r in results.values() if not r["success"])
    if error_count > 0 or not demo_success:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
