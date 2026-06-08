#!/usr/bin/env python3
"""
Update Artifact - Unified S3 + DynamoDB Sync Script
Sentra MVP - Policy & Sigma Rule Management Utility

Usage:
    # Update a policy
    python scripts/update_artifact.py --usecase policy --file policies/payment-agent-policy.yaml [--dry-run]
    
    # Update a Sigma rule
    python scripts/update_artifact.py --usecase sigma --file sigma_rules/llm/sql_injection.yaml [--dry-run]
    
Examples:
    # Update payment-agent policy
    python scripts/update_artifact.py --usecase policy --file sample-artifacts/policies/agents/payment-agent-policy.yaml
    
    # Update SQL injection Sigma rule
    python scripts/update_artifact.py --usecase sigma --file sample-artifacts/sigma_rules/llm/sql_injection.yaml
    
    # Dry-run (validate only, don't update)
    python scripts/update_artifact.py --usecase sigma --file sigma_rules/llm/sql_injection.yaml --dry-run

Features:
- Validates YAML schema (policy or Sigma rule)
- Uploads to S3 with versioning
- Updates DynamoDB metadata (tool count, patterns, hash, version ID)
- Supports dry-run mode for testing
- Atomic updates (rollback on failure)
"""

import sys
import os
import argparse
import hashlib
import yaml
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional

import boto3
from botocore.exceptions import ClientError

# Import schema validators
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'schemas'))
from sigma_rule_schema import SigmaRuleDocument

# AWS Configuration
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_PROFILE = os.environ.get('AWS_PROFILE', 'sentra')

# Table/Bucket Names (can be overridden via env vars)
POLICIES_METADATA_TABLE = os.environ.get('POLICIES_METADATA_TABLE', 'sentra-policies-metadata')
SIGMA_RULES_METADATA_TABLE = os.environ.get('SIGMA_RULES_METADATA_TABLE', 'sentra-sigma-rules-metadata')
ARTIFACTS_BUCKET = os.environ.get('ARTIFACTS_BUCKET', None)  # Must be set or auto-discovered


class ArtifactUpdateError(Exception):
    """Raised when artifact update fails"""
    pass


# ============================================================
# Policy Validation
# ============================================================

def validate_policy_schema(policy_data: Dict) -> Tuple[bool, str]:
    """
    Validate policy YAML structure
    
    Returns:
        (is_valid, error_message)
    """
    required_fields = [
        'schema_version', 'policy_id', 'agent_id', 'name', 
        'version', 'status', 'allowed_tools', 'policies'
    ]
    
    for field in required_fields:
        if field not in policy_data:
            return False, f"Missing required field: {field}"
    
    if not isinstance(policy_data['allowed_tools'], list):
        return False, "allowed_tools must be a list"
    
    if len(policy_data['allowed_tools']) == 0:
        return False, "allowed_tools cannot be empty"
    
    if not isinstance(policy_data['policies'], list):
        return False, "policies must be a list"
    
    if policy_data['status'] not in ['active', 'inactive', 'draft']:
        return False, f"Invalid status: {policy_data['status']}"
    
    return True, ""


# ============================================================
# Sigma Rule Validation
# ============================================================

def validate_sigma_rule_schema(rule_data: Dict) -> Tuple[bool, str]:
    """
    Validate Sigma rule YAML structure using Pydantic schema
    
    Returns:
        (is_valid, error_message)
    """
    try:
        # Convert date objects to strings (YAML parser converts dates automatically)
        if 'date' in rule_data and hasattr(rule_data['date'], 'isoformat'):
            rule_data['date'] = rule_data['date'].isoformat()
        if 'modified' in rule_data and hasattr(rule_data['modified'], 'isoformat'):
            rule_data['modified'] = rule_data['modified'].isoformat()
        
        # Use Pydantic model for validation
        SigmaRuleDocument(**rule_data)
        return True, ""
    except Exception as e:
        return False, str(e)


def count_sigma_patterns(rule_data: Dict) -> int:
    """Count detection patterns in Sigma rule"""
    detection = rule_data.get('detection', {})
    pattern_count = 0
    
    for key, value in detection.items():
        if key == 'condition':
            continue
        if isinstance(value, dict):
            for field, patterns in value.items():
                if '|contains' in field and isinstance(patterns, list):
                    pattern_count += len(patterns)
    
    return pattern_count


# ============================================================
# S3 Operations
# ============================================================

def get_artifacts_bucket() -> str:
    """
    Auto-discover artifacts bucket from CloudFormation stack
    """
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    cfn = session.client('cloudformation')
    
    try:
        response = cfn.describe_stacks(StackName="Sentra-DEV-Storage-Stack")
        outputs = response["Stacks"][0]["Outputs"]
        
        for output in outputs:
            if output["OutputKey"] == "ArtifactsBucketName":
                return output["OutputValue"]
    except ClientError as e:
        raise ArtifactUpdateError(f"Failed to discover artifacts bucket: {e}")
    
    raise ArtifactUpdateError("Could not find artifacts bucket. Set ARTIFACTS_BUCKET env var.")


def upload_to_s3(
    bucket: str,
    content: str,
    s3_key: str,
    metadata: Dict,
    dry_run: bool = False
) -> str:
    """
    Upload content to S3
    
    Returns:
        s3_version_id
    """
    print(f"\n📤 Uploading to S3:")
    print(f"   Bucket: {bucket}")
    print(f"   Key: {s3_key}")
    
    if dry_run:
        print("   [DRY-RUN] Skipping S3 upload")
        return "dry-run-version-id"
    
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    s3_client = session.client('s3')
    
    try:
        response = s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=content.encode('utf-8'),
            ContentType='application/x-yaml',
            Metadata=metadata
        )
        
        version_id = response.get('VersionId', '')
        print(f"   ✓ Uploaded successfully")
        print(f"   Version ID: {version_id}")
        
        return version_id
        
    except ClientError as e:
        raise ArtifactUpdateError(f"S3 upload failed: {e}")


# ============================================================
# Policy Update
# ============================================================

def update_policy(
    policy_data: Dict,
    policy_content: str,
    s3_bucket: str,
    dry_run: bool = False
) -> None:
    """Update policy in S3 and DynamoDB"""
    
    # Generate S3 key
    agent_id = policy_data['agent_id']
    version = policy_data['version']
    s3_key = f"policies/agents/{agent_id}/v{version}.yaml"
    
    # Upload to S3
    metadata = {
        'policy_id': policy_data['policy_id'],
        'agent_id': agent_id,
        'version': version,
        'uploaded_at': datetime.now(timezone.utc).isoformat()
    }
    
    s3_version_id = upload_to_s3(s3_bucket, policy_content, s3_key, metadata, dry_run)
    
    # Update DynamoDB
    update_policy_metadata(policy_data, policy_content, s3_bucket, s3_key, s3_version_id, dry_run)


def update_policy_metadata(
    policy_data: Dict,
    policy_content: str,
    s3_bucket: str,
    s3_key: str,
    s3_version_id: str,
    dry_run: bool = False
) -> None:
    """Update policy metadata in DynamoDB"""
    
    policy_id = policy_data['policy_id']
    content_hash = hashlib.sha256(policy_content.encode()).hexdigest()
    allowed_tools_count = len(policy_data['allowed_tools'])
    policies_count = len(policy_data['policies'])
    
    # Calculate severity breakdown
    severity_breakdown = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
    for policy in policy_data['policies']:
        severity = policy.get('severity', 'medium')
        if severity in severity_breakdown:
            severity_breakdown[severity] += 1

    # Cross-cloud metadata (Workstream 15) — keep this writer in sync with
    # seed_policies_metadata.py so the dashboard inventory and any metadata-only
    # consumers see platform / region / cross-cloud-dependency flags without
    # re-downloading the S3 YAML. Generic: derived from the policy doc, so any
    # agent (single- or cross-cloud) gets correct values.
    cross_cloud_deps = policy_data.get('cross_cloud_dependencies') or []
    platform = policy_data.get('platform', 'unknown')
    cloud_region = policy_data.get('cloud_region', 'unknown')

    print(f"\n📝 Updating DynamoDB:")
    print(f"   Table: {POLICIES_METADATA_TABLE}")
    print(f"   Policy ID: {policy_id}")
    print(f"   Tool count: {allowed_tools_count}")
    print(f"   Policy rules: {policies_count}")
    print(f"   Content hash: {content_hash[:32]}...")
    
    if dry_run:
        print("   [DRY-RUN] Skipping DynamoDB update")
        return
    
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    dynamodb = session.resource('dynamodb')
    table = dynamodb.Table(POLICIES_METADATA_TABLE)
    
    try:
        # Check if item exists
        response = table.get_item(Key={'policy_id': policy_id})
        item_exists = 'Item' in response
        
        if item_exists:
            # Update existing item
            table.update_item(
                Key={'policy_id': policy_id},
                UpdateExpression='''
                    SET allowed_tools_count = :tools_count,
                        policies_count = :policies_count,
                        content_hash = :hash,
                        s3_version_id = :vid,
                        s3_bucket = :bucket,
                        s3_key = :key,
                        #status = :status,
                        severity_breakdown = :severity,
                        version = :version,
                        agent_id = :agent_id,
                        #name = :name,
                        #platform = :platform,
                        cloud_region = :cloud_region,
                        has_cross_cloud_deps = :has_ccd,
                        cross_cloud_deps_count = :ccd_count,
                        updated_at = :updated_at
                ''',
                ExpressionAttributeNames={
                    '#status': 'status',
                    '#name': 'name',
                    '#platform': 'platform'
                },
                ExpressionAttributeValues={
                    ':tools_count': allowed_tools_count,
                    ':policies_count': policies_count,
                    ':hash': content_hash,
                    ':vid': s3_version_id,
                    ':bucket': s3_bucket,
                    ':key': s3_key,
                    ':status': policy_data['status'],
                    ':severity': severity_breakdown,
                    ':version': policy_data['version'],
                    ':agent_id': policy_data['agent_id'],
                    ':name': policy_data['name'],
                    ':platform': platform,
                    ':cloud_region': cloud_region,
                    ':has_ccd': len(cross_cloud_deps) > 0,
                    ':ccd_count': len(cross_cloud_deps),
                    ':updated_at': datetime.now(timezone.utc).isoformat()
                }
            )
            print(f"   ✓ Updated existing metadata")
        else:
            # Create new item
            table.put_item(
                Item={
                    'policy_id': policy_id,
                    'agent_id': policy_data['agent_id'],
                    'name': policy_data['name'],
                    'version': policy_data['version'],
                    'status': policy_data['status'],
                    'schema_version': policy_data['schema_version'],
                    'allowed_tools_count': allowed_tools_count,
                    'policies_count': policies_count,
                    'severity_breakdown': severity_breakdown,
                    'content_hash': content_hash,
                    's3_bucket': s3_bucket,
                    's3_key': s3_key,
                    's3_version_id': s3_version_id,
                    'platform': platform,
                    'cloud_region': cloud_region,
                    'has_cross_cloud_deps': len(cross_cloud_deps) > 0,
                    'cross_cloud_deps_count': len(cross_cloud_deps),
                    'created_at': policy_data.get('created_at', datetime.now(timezone.utc).isoformat()),
                    'created_by': policy_data.get('created_by', 'admin'),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }
            )
            print(f"   ✓ Created new metadata entry")
        
    except ClientError as e:
        raise ArtifactUpdateError(f"DynamoDB update failed: {e}")


# ============================================================
# Sigma Rule Update
# ============================================================

def update_sigma_rule(
    rule_data: Dict,
    rule_content: str,
    s3_bucket: str,
    dry_run: bool = False
) -> None:
    """Update Sigma rule in S3 and DynamoDB"""
    
    # Generate S3 key (preserve existing structure)
    rule_id = rule_data['id']
    # Extract filename from rule_id or use title
    filename = rule_id.replace('sigma-llm-', '') + '.yaml'
    s3_key = f"sigma_rules/llm/{filename}"
    
    # Upload to S3
    metadata = {
        'rule_id': rule_id,
        'title': rule_data['title'],
        'level': rule_data['level'],
        'uploaded_at': datetime.now(timezone.utc).isoformat()
    }
    
    s3_version_id = upload_to_s3(s3_bucket, rule_content, s3_key, metadata, dry_run)
    
    # Update DynamoDB
    update_sigma_rule_metadata(rule_data, rule_content, s3_bucket, s3_key, s3_version_id, dry_run)


def update_sigma_rule_metadata(
    rule_data: Dict,
    rule_content: str,
    s3_bucket: str,
    s3_key: str,
    s3_version_id: str,
    dry_run: bool = False
) -> None:
    """Update Sigma rule metadata in DynamoDB"""
    
    rule_id = rule_data['id']
    content_hash = hashlib.sha256(rule_content.encode()).hexdigest()
    patterns_count = count_sigma_patterns(rule_data)
    
    # Get version (use modified date if available)
    version = rule_data.get('modified', rule_data.get('date', '1.0.0'))
    if hasattr(version, 'isoformat'):
        version = version.isoformat()
    else:
        version = str(version)
    
    print(f"\n📝 Updating DynamoDB:")
    print(f"   Table: {SIGMA_RULES_METADATA_TABLE}")
    print(f"   Rule ID: {rule_id}")
    print(f"   Patterns count: {patterns_count}")
    print(f"   Level: {rule_data['level']}")
    print(f"   Content hash: {content_hash[:32]}...")
    
    if dry_run:
        print("   [DRY-RUN] Skipping DynamoDB update")
        return
    
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    dynamodb = session.resource('dynamodb')
    table = dynamodb.Table(SIGMA_RULES_METADATA_TABLE)
    
    try:
        # Check if item exists
        response = table.get_item(Key={'rule_id': rule_id})
        item_exists = 'Item' in response
        
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        if item_exists:
            # Update existing item
            table.update_item(
                Key={'rule_id': rule_id},
                UpdateExpression='''
                    SET title = :title,
                        description = :description,
                        #status = :status,
                        #level = :level,
                        version = :version,
                        s3_bucket = :bucket,
                        s3_key = :key,
                        s3_version_id = :vid,
                        patterns_count = :patterns,
                        tags = :tags,
                        content_hash = :hash,
                        author = :author,
                        updated_at = :updated_at
                ''',
                ExpressionAttributeNames={
                    '#status': 'status',
                    '#level': 'level'
                },
                ExpressionAttributeValues={
                    ':title': rule_data['title'],
                    ':description': rule_data.get('description', ''),
                    ':status': rule_data['status'],
                    ':level': rule_data['level'],
                    ':version': version,
                    ':bucket': s3_bucket,
                    ':key': s3_key,
                    ':vid': s3_version_id,
                    ':patterns': patterns_count,
                    ':tags': rule_data.get('tags', []),
                    ':hash': content_hash,
                    ':author': rule_data.get('author', 'Unknown'),
                    ':updated_at': timestamp
                }
            )
            print(f"   ✓ Updated existing metadata")
        else:
            # Create new item
            table.put_item(
                Item={
                    'rule_id': rule_id,
                    'title': rule_data['title'],
                    'description': rule_data.get('description', ''),
                    'status': rule_data['status'],
                    'level': rule_data['level'],
                    'version': version,
                    's3_bucket': s3_bucket,
                    's3_key': s3_key,
                    's3_version_id': s3_version_id,
                    'patterns_count': patterns_count,
                    'tags': rule_data.get('tags', []),
                    'stats': {
                        'match_count_24h': 0,
                        'match_count_7d': 0,
                        'last_matched': None
                    },
                    'content_hash': content_hash,
                    'schema_version': '1.0',
                    'created_at': timestamp,
                    'created_by': 'update-script',
                    'author': rule_data.get('author', 'Unknown'),
                    'updated_at': timestamp
                }
            )
            print(f"   ✓ Created new metadata entry")
        
    except ClientError as e:
        raise ArtifactUpdateError(f"DynamoDB update failed: {e}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Update policy or Sigma rule in S3 and DynamoDB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--usecase',
        required=True,
        choices=['policy', 'sigma'],
        help='Type of artifact to update (policy or sigma)'
    )
    parser.add_argument(
        '--file',
        required=True,
        help='Path to YAML file (policy or Sigma rule)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate only, do not update S3/DynamoDB'
    )
    parser.add_argument(
        '--bucket',
        help='Override S3 bucket name (auto-discovered by default)'
    )
    
    args = parser.parse_args()
    
    # Header
    print("=" * 70)
    print(f"Sentra Artifact Update Script - {args.usecase.upper()}")
    print("=" * 70)
    
    if args.dry_run:
        print("🔍 DRY-RUN MODE - No changes will be made")
    
    # Step 1: Load and parse YAML
    print(f"\n📖 Loading file: {args.file}")
    
    if not os.path.exists(args.file):
        print(f"❌ Error: File not found: {args.file}")
        sys.exit(1)
    
    try:
        with open(args.file, 'r') as f:
            content = f.read()
            data = yaml.safe_load(content)
    except Exception as e:
        print(f"❌ Error: Failed to parse YAML: {e}")
        sys.exit(1)
    
    # Step 2: Validate schema
    print(f"\n🔍 Validating {args.usecase} schema...")
    
    if args.usecase == 'policy':
        print(f"   ✓ Loaded policy: {data.get('name', 'Unknown')}")
        print(f"   Policy ID: {data.get('policy_id', 'Unknown')}")
        print(f"   Agent ID: {data.get('agent_id', 'Unknown')}")
        print(f"   Version: {data.get('version', 'Unknown')}")
        
        is_valid, error_msg = validate_policy_schema(data)
        if not is_valid:
            print(f"❌ Validation failed: {error_msg}")
            sys.exit(1)
        
        print(f"   ✓ Schema valid")
        print(f"   Allowed tools: {len(data['allowed_tools'])}")
        print(f"   Policy rules: {len(data['policies'])}")
        
    elif args.usecase == 'sigma':
        print(f"   ✓ Loaded Sigma rule: {data.get('title', 'Unknown')}")
        print(f"   Rule ID: {data.get('id', 'Unknown')}")
        print(f"   Level: {data.get('level', 'Unknown')}")
        print(f"   Status: {data.get('status', 'Unknown')}")
        
        is_valid, error_msg = validate_sigma_rule_schema(data)
        if not is_valid:
            print(f"❌ Validation failed: {error_msg}")
            sys.exit(1)
        
        print(f"   ✓ Schema valid")
        print(f"   Patterns: {count_sigma_patterns(data)}")
        print(f"   Tags: {len(data.get('tags', []))}")
    
    # Step 3: Get S3 bucket
    s3_bucket = args.bucket or ARTIFACTS_BUCKET
    if not s3_bucket:
        print(f"\n🔍 Auto-discovering S3 bucket...")
        try:
            s3_bucket = get_artifacts_bucket()
            print(f"   ✓ Found: {s3_bucket}")
        except ArtifactUpdateError as e:
            print(f"❌ {e}")
            sys.exit(1)
    
    # Step 4: Update artifact
    try:
        if args.usecase == 'policy':
            update_policy(data, content, s3_bucket, dry_run=args.dry_run)
        elif args.usecase == 'sigma':
            update_sigma_rule(data, content, s3_bucket, dry_run=args.dry_run)
    except ArtifactUpdateError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # Success summary
    print("\n" + "=" * 70)
    if args.dry_run:
        print("✓ DRY-RUN COMPLETE - Validation passed, no changes made")
    else:
        print(f"✓ {args.usecase.upper()} UPDATE COMPLETE")
        print(f"\nSummary:")
        if args.usecase == 'policy':
            print(f"  Policy ID: {data['policy_id']}")
            print(f"  Agent: {data['agent_id']}")
        elif args.usecase == 'sigma':
            print(f"  Rule ID: {data['id']}")
            print(f"  Title: {data['title']}")
        print(f"  S3 Bucket: {s3_bucket}")
        print(f"  DynamoDB: {SIGMA_RULES_METADATA_TABLE if args.usecase == 'sigma' else POLICIES_METADATA_TABLE}")
    print("=" * 70)


if __name__ == '__main__':
    main()
