#!/usr/bin/env python3
"""
Sentra MVP - Policy Metadata Seed Script

Seeds sentra-policies-metadata DynamoDB table with policy metadata.
Policy content is stored in S3, metadata in DynamoDB.

Requirements:
    pip install boto3 pyyaml

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    # Run the script
    python scripts/seed_policies_metadata.py

    # Dry run (preview without writing)
    python scripts/seed_policies_metadata.py --dry-run

    # Force overwrite existing items
    python scripts/seed_policies_metadata.py --force

Reference: LLD 06 Section 2.3, 3.3 (Policy Metadata Registry)
"""

import argparse
import boto3
import hashlib
import sys
import yaml
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


# AWS Configuration
AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"
TABLE_NAME = "sentra-policies-metadata"


def get_timestamp() -> str:
    """Generate ISO 8601 timestamp with Z suffix"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_s3_bucket_name() -> str:
    """Get the artifacts bucket name from CloudFormation outputs"""
    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        cf_client = session.client("cloudformation")

        response = cf_client.describe_stacks(StackName="Sentra-DEV-Storage-Stack")
        outputs = response["Stacks"][0]["Outputs"]

        for output in outputs:
            if output["OutputKey"] == "ArtifactsBucketName":
                return output["OutputValue"]

        raise Exception("ArtifactsBucketName output not found in stack")
    except Exception as e:
        raise Exception(f"Failed to get S3 bucket name: {e}")



def download_and_parse_policy(
    s3_client, bucket_name: str, s3_key: str
) -> Dict[str, Any]:
    """
    Download policy YAML from S3 and parse it

    Args:
        s3_client: Boto3 S3 client
        bucket_name: S3 bucket name
        s3_key: S3 object key

    Returns:
        Parsed policy dictionary
    """
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        content = response["Body"].read().decode("utf-8")
        policy = yaml.safe_load(content)
        return policy, content
    except Exception as e:
        raise Exception(f"Failed to download/parse policy from s3://{bucket_name}/{s3_key}: {e}")


def calculate_content_hash(content: str) -> str:
    """Calculate SHA256 hash of policy content"""
    return hashlib.sha256(content.encode()).hexdigest()


def get_s3_version_id(
    s3_client, bucket_name: str, s3_key: str
) -> Optional[str]:
    """Get S3 version ID for an object"""
    try:
        response = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
        return response.get("VersionId")
    except Exception:
        return None


def count_policies_by_severity(policy: Dict[str, Any]) -> Dict[str, int]:
    """Count policies by severity level"""
    severity_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    policies = policy.get("policies", [])
    for pol in policies:
        severity = pol.get("severity", "medium").lower()
        if severity in severity_counts:
            severity_counts[severity] += 1

    return severity_counts



def get_policy_metadata_items(
    s3_client, bucket_name: str
) -> List[Dict[str, Any]]:
    """
    Generate policy metadata items by reading from S3

    Schema (per LLD 06 Section 2.3):
    - policy_id (STRING) - Primary Key
    - agent_id (STRING) - For agent-index GSI
    - name (STRING)
    - version (STRING)
    - status (STRING) - "active" | "inactive" | "deprecated"
    - s3_bucket (STRING)
    - s3_key (STRING)
    - s3_version_id (STRING) - Optional
    - allowed_tools_count (NUMBER)
    - policies_count (NUMBER)
    - severity_breakdown (MAP) - {low: N, medium: N, high: N, critical: N}
    - content_hash (STRING) - SHA256 hash
    - schema_version (STRING)
    - created_at (STRING) - ISO 8601 timestamp
    - created_by (STRING)

    Returns:
        List of policy metadata dictionaries
    """
    timestamp = get_timestamp()
    metadata_items = []

    # Define policy files to process.
    # Workstream 15 added the bottom two entries for cross-cloud demo scenarios.
    policy_files = [
        {
            "agent_id": "customer-query-agent",
            "s3_key": "policies/agents/customer-query-agent/v1.0.0.yaml",
        },
        {
            "agent_id": "payment-agent",
            "s3_key": "policies/agents/payment-agent/v1.0.0.yaml",
        },
        {
            "agent_id": "sentra-mvp-customer-service-agent",
            "s3_key": "policies/agents/sentra-mvp-customer-service-agent/v1.0.0.yaml",
        },
        {
            "agent_id": "azure-verification-agent",
            "s3_key": "policies/agents/azure-verification-agent/v1.0.0.yaml",
        },
    ]

    for policy_file in policy_files:
        agent_id = policy_file["agent_id"]
        s3_key = policy_file["s3_key"]

        print(f"  Processing: {s3_key}")

        # Download and parse policy
        policy, content = download_and_parse_policy(s3_client, bucket_name, s3_key)

        # Calculate metadata
        content_hash = calculate_content_hash(content)
        s3_version_id = get_s3_version_id(s3_client, bucket_name, s3_key)
        severity_breakdown = count_policies_by_severity(policy)

        # Build metadata item.
        # Cross-cloud fields (Workstream 15): platform, cloud_region, and a
        # boolean flag for whether this policy has any cross_cloud_dependencies
        # rules — surfaced for dashboard rendering without re-downloading YAML.
        cross_cloud_deps = policy.get("cross_cloud_dependencies", []) or []
        metadata_item = {
            "policy_id": policy.get("policy_id"),
            "agent_id": agent_id,
            "name": policy.get("name"),
            "version": policy.get("version"),
            "status": policy.get("status", "active"),
            "s3_bucket": bucket_name,
            "s3_key": s3_key,
            "allowed_tools_count": len(policy.get("allowed_tools", [])),
            "policies_count": len(policy.get("policies", [])),
            "severity_breakdown": severity_breakdown,
            "content_hash": content_hash,
            "schema_version": policy.get("schema_version", "1.0"),
            "platform": policy.get("platform", "unknown"),
            "cloud_region": policy.get("cloud_region", "unknown"),
            "has_cross_cloud_deps": len(cross_cloud_deps) > 0,
            "cross_cloud_deps_count": len(cross_cloud_deps),
            "created_at": timestamp,
            "created_by": policy.get("created_by", "system"),
        }

        # Add s3_version_id if available
        if s3_version_id:
            metadata_item["s3_version_id"] = s3_version_id

        metadata_items.append(metadata_item)

    return metadata_items



def seed_policies_metadata(dry_run: bool = False, force: bool = False) -> bool:
    """
    Seed policy metadata table with metadata from S3 policies

    Args:
        dry_run: If True, preview changes without writing
        force: If True, overwrite existing items

    Returns:
        True if successful, False otherwise
    """
    print("=" * 80)
    print("Sentra MVP - Policy Metadata Seed Script")
    print("=" * 80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No data will be written\n")

    # Get S3 bucket name
    print("\nGetting S3 bucket name from CloudFormation...")
    try:
        bucket_name = get_s3_bucket_name()
        print(f"  ✅ S3 Bucket: {bucket_name}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

    # Set up boto3 clients
    print(f"\nConnecting to AWS (profile: {AWS_PROFILE}, region: {AWS_REGION})...")
    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        s3_client = session.client("s3")
        dynamodb = session.resource("dynamodb")
        table = dynamodb.Table(TABLE_NAME)

        # Verify table exists
        table.table_status
        print(f"  ✅ Connected to table: {TABLE_NAME}")
    except Exception as e:
        print(f"  ❌ Error: Could not connect to resources")
        print(f"  Error details: {e}")
        return False

    # Get policy metadata from S3
    print(f"\n" + "=" * 80)
    print("Reading Policy Files from S3")
    print("=" * 80)

    try:
        metadata_items = get_policy_metadata_items(s3_client, bucket_name)
        print(f"\n✅ Processed {len(metadata_items)} policy files")
    except Exception as e:
        print(f"\n❌ Error processing policy files: {e}")
        return False

    if dry_run:
        print("\n" + "=" * 80)
        print("Preview of Policy Metadata")
        print("=" * 80)

        for item in metadata_items:
            print(f"\nPolicy: {item['name']}")
            print(f"  ID: {item['policy_id']}")
            print(f"  Agent: {item['agent_id']}")
            print(f"  Version: {item['version']}")
            print(f"  Status: {item['status']}")
            print(f"  S3 Key: {item['s3_key']}")
            print(f"  Allowed Tools: {item['allowed_tools_count']}")
            print(f"  Policies: {item['policies_count']}")
            print(f"  Severity Breakdown: {item['severity_breakdown']}")
            print(f"  Content Hash: {item['content_hash'][:16]}...")

        print("\n" + "=" * 80)
        print("✅ Dry run complete - no data written")
        print("=" * 80)
        return True

    # Write metadata to DynamoDB
    print(f"\n" + "=" * 80)
    print("Writing Policy Metadata to DynamoDB")
    print("=" * 80)

    written_count = 0
    skipped_count = 0
    error_count = 0

    for item in metadata_items:
        policy_id = item["policy_id"]

        try:
            # Check if item exists (unless force mode)
            if not force:
                response = table.get_item(Key={"policy_id": policy_id})
                if "Item" in response:
                    print(
                        f"  ⚠️  Skipping {policy_id} - already exists (use --force to overwrite)"
                    )
                    skipped_count += 1
                    continue

            # Write item
            table.put_item(Item=item)
            print(f"  ✅ Written: {policy_id} ({item['agent_id']})")
            written_count += 1

        except Exception as e:
            print(f"  ❌ Error writing {policy_id}: {e}")
            error_count += 1

    # Summary
    print(f"\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"  Written: {written_count} policy metadata items")
    print(f"  Skipped: {skipped_count} items")
    print(f"  Errors: {error_count} items")

    if error_count > 0:
        print(f"\n  ⚠️  Some items failed to write")
        return False
    elif written_count == 0 and skipped_count > 0:
        print(f"\n  ℹ️  All items already exist - use --force to overwrite")
        return True
    else:
        print(f"\n  ✅ Successfully seeded {written_count} policy metadata items")
        return True



def verify_policies_metadata() -> bool:
    """
    Verify policy metadata was written successfully

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
        # Workstream 15: 2 legacy agents + 2 cross-cloud agents = 4
        expected_count = 4  # customer-query-agent, payment-agent, sentra-mvp-customer-service-agent, azure-verification-agent

        print(f"\nPolicy metadata count:")
        print(f"  Expected: {expected_count} items")
        print(f"  Actual: {actual_count} items")

        if actual_count == expected_count:
            print(f"  ✅ Verification passed!")

            # Query by agent_id using GSI
            print(f"\nQuerying policies for payment-agent using agent-index GSI...")
            response = table.query(
                IndexName="agent-index",
                KeyConditionExpression="agent_id = :agent_id",
                ExpressionAttributeValues={":agent_id": "payment-agent"},
            )
            payment_policies = response["Count"]
            print(f"  Payment agent policies: {payment_policies}")

            print(f"\nQuerying active policies using status-index GSI...")
            response = table.query(
                IndexName="status-index",
                KeyConditionExpression="#status = :status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": "active"},
            )
            active_policies = response["Count"]
            print(f"  Active policies: {active_policies}")

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
        description="Seed sentra-policies-metadata DynamoDB table with policy metadata from S3"
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
        success = verify_policies_metadata()
        sys.exit(0 if success else 1)

    # Run seeding
    success = seed_policies_metadata(dry_run=args.dry_run, force=args.force)

    if not success:
        sys.exit(1)

    # Run verification (unless dry run)
    if not args.dry_run:
        verify_policies_metadata()

    print(f"\n" + "=" * 80)
    print("🎉 Policy metadata seeding complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
