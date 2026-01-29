#!/usr/bin/env python3
"""
Sentra MVP - Sigma Rules Metadata Seed Script

Seeds sentra-sigma-rules-metadata DynamoDB table with Sigma rule metadata.
Rule content is stored in S3, metadata in DynamoDB.

Requirements:
    pip install boto3 pyyaml

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    # Run the script
    python scripts/seed_sigma_rules_metadata.py

    # Dry run (preview without writing)
    python scripts/seed_sigma_rules_metadata.py --dry-run

    # Force overwrite existing items
    python scripts/seed_sigma_rules_metadata.py --force

Reference: LLD 06 Section 2.4, 3.3 (Sigma Rules Metadata Registry)
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
TABLE_NAME = "sentra-sigma-rules-metadata"


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



def download_and_parse_rule(
    s3_client, bucket_name: str, s3_key: str
) -> tuple[Dict[str, Any], str]:
    """
    Download Sigma rule YAML from S3 and parse it

    Args:
        s3_client: Boto3 S3 client
        bucket_name: S3 bucket name
        s3_key: S3 object key

    Returns:
        Tuple of (parsed rule dictionary, raw content string)
    """
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        content = response["Body"].read().decode("utf-8")
        rule = yaml.safe_load(content)
        return rule, content
    except Exception as e:
        raise Exception(f"Failed to download/parse rule from s3://{bucket_name}/{s3_key}: {e}")


def calculate_content_hash(content: str) -> str:
    """Calculate SHA256 hash of rule content"""
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


def count_detection_patterns(rule: Dict[str, Any]) -> int:
    """Count number of detection patterns in a Sigma rule"""
    detection = rule.get("detection", {})
    # Count all keys except 'condition'
    pattern_count = len([k for k in detection.keys() if k != "condition"])
    return pattern_count


def list_s3_sigma_rules(s3_client, bucket_name: str, prefix: str = "sigma_rules/llm/") -> List[str]:
    """List all Sigma rule files in S3"""
    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        if "Contents" not in response:
            return []

        # Filter for YAML files only
        rule_keys = [
            obj["Key"]
            for obj in response["Contents"]
            if obj["Key"].endswith(".yaml") or obj["Key"].endswith(".yml")
        ]
        return rule_keys
    except Exception as e:
        raise Exception(f"Failed to list S3 objects: {e}")



def get_sigma_rule_metadata_items(
    s3_client, bucket_name: str
) -> List[Dict[str, Any]]:
    """
    Generate Sigma rule metadata items by reading from S3

    Schema (per LLD 06 Section 2.4):
    - rule_id (STRING) - Primary Key
    - title (STRING)
    - description (STRING)
    - status (STRING) - "stable" | "experimental" | "deprecated"
    - level (STRING) - "critical" | "high" | "medium" | "low"
    - version (STRING)
    - s3_bucket (STRING)
    - s3_key (STRING)
    - s3_version_id (STRING) - Optional
    - patterns_count (NUMBER)
    - tags (LIST of STRING)
    - stats (MAP) - {match_count_24h: N, match_count_7d: N, last_matched: timestamp}
    - content_hash (STRING) - SHA256 hash
    - schema_version (STRING)
    - created_at (STRING) - ISO 8601 timestamp
    - created_by (STRING)
    - author (STRING)

    Returns:
        List of Sigma rule metadata dictionaries
    """
    timestamp = get_timestamp()
    metadata_items = []

    # List all Sigma rules in S3
    print(f"  Listing Sigma rules from S3...")
    rule_keys = list_s3_sigma_rules(s3_client, bucket_name)
    print(f"  Found {len(rule_keys)} Sigma rule files")

    for s3_key in rule_keys:
        print(f"  Processing: {s3_key}")

        try:
            # Download and parse rule
            rule, content = download_and_parse_rule(s3_client, bucket_name, s3_key)

            # Calculate metadata
            content_hash = calculate_content_hash(content)
            s3_version_id = get_s3_version_id(s3_client, bucket_name, s3_key)
            patterns_count = count_detection_patterns(rule)

            # Build metadata item
            version = rule.get("modified", rule.get("date", "1.0.0"))
            # Convert date objects to strings
            if hasattr(version, "isoformat"):
                version = version.isoformat()
            else:
                version = str(version)

            metadata_item = {
                "rule_id": rule.get("id"),
                "title": rule.get("title"),
                "description": rule.get("description", ""),
                "status": rule.get("status", "experimental"),
                "level": rule.get("level", "medium"),
                "version": version,
                "s3_bucket": bucket_name,
                "s3_key": s3_key,
                "patterns_count": patterns_count,
                "tags": rule.get("tags", []),
                "stats": {
                    "match_count_24h": 0,
                    "match_count_7d": 0,
                    "last_matched": None,
                },
                "content_hash": content_hash,
                "schema_version": "1.0",
                "created_at": timestamp,
                "created_by": "system",
                "author": rule.get("author", "Unknown"),
            }

            # Add s3_version_id if available
            if s3_version_id:
                metadata_item["s3_version_id"] = s3_version_id

            metadata_items.append(metadata_item)

        except Exception as e:
            print(f"    ⚠️  Error processing {s3_key}: {e}")
            continue

    return metadata_items



def seed_sigma_rules_metadata(dry_run: bool = False, force: bool = False) -> bool:
    """
    Seed Sigma rules metadata table with metadata from S3 rules

    Args:
        dry_run: If True, preview changes without writing
        force: If True, overwrite existing items

    Returns:
        True if successful, False otherwise
    """
    print("=" * 80)
    print("Sentra MVP - Sigma Rules Metadata Seed Script")
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

    # Get Sigma rule metadata from S3
    print(f"\n" + "=" * 80)
    print("Reading Sigma Rule Files from S3")
    print("=" * 80)

    try:
        metadata_items = get_sigma_rule_metadata_items(s3_client, bucket_name)
        print(f"\n✅ Processed {len(metadata_items)} Sigma rule files")
    except Exception as e:
        print(f"\n❌ Error processing Sigma rule files: {e}")
        return False

    if dry_run:
        print("\n" + "=" * 80)
        print("Preview of Sigma Rule Metadata")
        print("=" * 80)

        # Group by level
        by_level = {}
        for item in metadata_items:
            level = item["level"]
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(item)

        for level in ["critical", "high", "medium", "low"]:
            if level in by_level:
                print(f"\n{level.upper()} Severity Rules ({len(by_level[level])}):")
                for item in by_level[level]:
                    print(f"  - {item['rule_id']}: {item['title']}")
                    print(f"    Status: {item['status']}, Patterns: {item['patterns_count']}")

        print("\n" + "=" * 80)
        print("Sample Rule Details")
        print("=" * 80)
        if metadata_items:
            sample = metadata_items[0]
            print(f"\nRule: {sample['title']}")
            print(f"  ID: {sample['rule_id']}")
            print(f"  Level: {sample['level']}")
            print(f"  Status: {sample['status']}")
            print(f"  S3 Key: {sample['s3_key']}")
            print(f"  Patterns: {sample['patterns_count']}")
            print(f"  Tags: {', '.join(sample['tags'][:5])}")
            print(f"  Content Hash: {sample['content_hash'][:16]}...")

        print("\n" + "=" * 80)
        print("✅ Dry run complete - no data written")
        print("=" * 80)
        return True

    # Write metadata to DynamoDB
    print(f"\n" + "=" * 80)
    print("Writing Sigma Rule Metadata to DynamoDB")
    print("=" * 80)

    written_count = 0
    skipped_count = 0
    error_count = 0

    for item in metadata_items:
        rule_id = item["rule_id"]

        try:
            # Check if item exists (unless force mode)
            if not force:
                response = table.get_item(Key={"rule_id": rule_id})
                if "Item" in response:
                    print(
                        f"  ⚠️  Skipping {rule_id} - already exists (use --force to overwrite)"
                    )
                    skipped_count += 1
                    continue

            # Write item
            table.put_item(Item=item)
            print(f"  ✅ Written: {rule_id} ({item['level']})")
            written_count += 1

        except Exception as e:
            print(f"  ❌ Error writing {rule_id}: {e}")
            error_count += 1

    # Summary
    print(f"\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"  Written: {written_count} Sigma rule metadata items")
    print(f"  Skipped: {skipped_count} items")
    print(f"  Errors: {error_count} items")

    if error_count > 0:
        print(f"\n  ⚠️  Some items failed to write")
        return False
    elif written_count == 0 and skipped_count > 0:
        print(f"\n  ℹ️  All items already exist - use --force to overwrite")
        return True
    else:
        print(f"\n  ✅ Successfully seeded {written_count} Sigma rule metadata items")
        return True



def verify_sigma_rules_metadata() -> bool:
    """
    Verify Sigma rule metadata was written successfully

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

        print(f"\nSigma rule metadata count:")
        print(f"  Actual: {actual_count} items")

        if actual_count > 0:
            print(f"  ✅ Verification passed!")

            # Query by level using GSI
            print(f"\nQuerying high-severity rules using level-index GSI...")
            response = table.query(
                IndexName="level-index",
                KeyConditionExpression="#level = :level",
                ExpressionAttributeNames={"#level": "level"},
                ExpressionAttributeValues={":level": "high"},
            )
            high_rules = response["Count"]
            print(f"  High-severity rules: {high_rules}")

            print(f"\nQuerying critical-severity rules using level-index GSI...")
            response = table.query(
                IndexName="level-index",
                KeyConditionExpression="#level = :level",
                ExpressionAttributeNames={"#level": "level"},
                ExpressionAttributeValues={":level": "critical"},
            )
            critical_rules = response["Count"]
            print(f"  Critical-severity rules: {critical_rules}")

            print(f"\nQuerying stable rules using status-index GSI...")
            response = table.query(
                IndexName="status-index",
                KeyConditionExpression="#status = :status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": "stable"},
            )
            stable_rules = response["Count"]
            print(f"  Stable rules: {stable_rules}")

            print(f"  ✅ GSI queries successful")

            return True
        else:
            print(f"  ⚠️  Warning: No items found!")
            return False

    except Exception as e:
        print(f"  ❌ Verification failed: {e}")
        return False


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description="Seed sentra-sigma-rules-metadata DynamoDB table with Sigma rule metadata from S3"
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
        success = verify_sigma_rules_metadata()
        sys.exit(0 if success else 1)

    # Run seeding
    success = seed_sigma_rules_metadata(dry_run=args.dry_run, force=args.force)

    if not success:
        sys.exit(1)

    # Run verification (unless dry run)
    if not args.dry_run:
        verify_sigma_rules_metadata()

    print(f"\n" + "=" * 80)
    print("🎉 Sigma rule metadata seeding complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
