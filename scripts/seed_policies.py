#!/usr/bin/env python3
"""
Policy Seeding Script

Loads agent policies from config/agent_policies.yaml into DynamoDB.
Run this script after infrastructure deployment to populate policies.

Usage:
    python scripts/seed_policies.py                    # Load policies
    python scripts/seed_policies.py --dry-run          # Preview changes
    python scripts/seed_policies.py --force            # Overwrite existing
    python scripts/seed_policies.py --delete-all       # Delete all policies (dangerous!)

Environment Variables:
    AWS_PROFILE: AWS profile to use (default: sentra)
    AWS_REGION: AWS region (default: us-east-1)
"""
import os
import sys
import yaml
import argparse
import time
from datetime import datetime
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'security-controller'))

# Configuration
DEFAULT_PROFILE = 'sentra'
DEFAULT_REGION = 'us-east-1'
POLICIES_TABLE = 'sentra-policies'
CONFIG_FILE = 'config/agent_policies.yaml'


class PolicySeeder:
    """Handles loading policies from YAML into DynamoDB"""
    
    def __init__(self, profile: str = None, region: str = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.region = region or os.environ.get('AWS_REGION', DEFAULT_REGION)
        
        # Initialize boto3 session
        if profile:
            session = boto3.Session(profile_name=profile, region_name=self.region)
        else:
            session = boto3.Session(region_name=self.region)
        
        self.dynamodb = session.resource('dynamodb')
        self.table = self.dynamodb.Table(POLICIES_TABLE)
        
        print(f"🔧 Configuration:")
        print(f"   Region: {self.region}")
        print(f"   Profile: {profile or 'default'}")
        print(f"   Table: {POLICIES_TABLE}")
        print(f"   Dry Run: {self.dry_run}")
        print()
    
    def load_policies_from_yaml(self, config_path: str) -> Dict:
        """Load policies from YAML file"""
        try:
            with open(config_path, 'r') as f:
                policies = yaml.safe_load(f)
            
            if not policies:
                raise ValueError("Empty policies file")
            
            print(f"✅ Loaded {len(policies)} policies from {config_path}")
            return policies
        
        except FileNotFoundError:
            print(f"❌ Error: Config file not found: {config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"❌ Error: Invalid YAML format: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error loading policies: {e}")
            sys.exit(1)
    
    def validate_policy(self, agent_id: str, policy: Dict) -> bool:
        """Validate policy structure"""
        required_fields = ['allowed_tools', 'allowed_agents', 'max_calls_per_minute']
        
        for field in required_fields:
            if field not in policy:
                print(f"❌ Policy for '{agent_id}' missing required field: {field}")
                return False
        
        # Validate types
        if not isinstance(policy['allowed_tools'], list):
            print(f"❌ Policy for '{agent_id}': allowed_tools must be a list")
            return False
        
        if not isinstance(policy['allowed_agents'], list):
            print(f"❌ Policy for '{agent_id}': allowed_agents must be a list")
            return False
        
        if not isinstance(policy['max_calls_per_minute'], int):
            print(f"❌ Policy for '{agent_id}': max_calls_per_minute must be an integer")
            return False
        
        return True
    
    def transform_to_dynamodb_item(self, agent_id: str, policy: Dict) -> Dict:
        """Transform YAML policy to DynamoDB item format"""
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        return {
            'policy_id': f"pol-{agent_id}-001",
            'agent_id': agent_id,
            'version': 1,  # NUMBER type for GSI sort key
            'is_active': True,
            'allowed_tools': policy['allowed_tools'],
            'allowed_agents': policy['allowed_agents'],
            'max_calls_per_minute': policy['max_calls_per_minute'],
            'created_at': timestamp,
            'updated_at': timestamp
        }
    
    def check_existing_policy(self, agent_id: str) -> bool:
        """Check if policy already exists for agent"""
        try:
            # Use agent-version-index GSI (existing in storage stack)
            response = self.table.query(
                IndexName='agent-version-index',
                KeyConditionExpression='agent_id = :agent_id',
                ExpressionAttributeValues={':agent_id': agent_id}
            )
            return len(response.get('Items', [])) > 0
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"⚠️  Warning: GSI 'agent-version-index' not found. Skipping duplicate check.")
                return False
            raise
    
    def seed_policies(self, policies: Dict, force: bool = False) -> None:
        """Seed policies into DynamoDB"""
        print(f"\n📝 Processing {len(policies)} policies...\n")
        
        items_to_write = []
        skipped = []
        
        for agent_id, policy in policies.items():
            print(f"Processing: {agent_id}")
            
            # Validate policy
            if not self.validate_policy(agent_id, policy):
                print(f"   ❌ Validation failed - skipping\n")
                skipped.append(agent_id)
                continue
            
            # Check if exists
            if not force and self.check_existing_policy(agent_id):
                print(f"   ⚠️  Policy already exists (use --force to overwrite)")
                print(f"   Skipping...\n")
                skipped.append(agent_id)
                continue
            
            # Transform to DynamoDB item
            item = self.transform_to_dynamodb_item(agent_id, policy)
            items_to_write.append(item)
            
            print(f"   ✅ Ready to write:")
            print(f"      Policy ID: {item['policy_id']}")
            print(f"      Tools: {len(item['allowed_tools'])} ({', '.join(item['allowed_tools'][:3])}...)")
            print(f"      Can invoke: {len(item['allowed_agents'])} agents")
            print(f"      Rate limit: {item['max_calls_per_minute']} calls/min\n")
        
        # Summary
        print(f"\n📊 Summary:")
        print(f"   Total policies: {len(policies)}")
        print(f"   To write: {len(items_to_write)}")
        print(f"   Skipped: {len(skipped)}")
        
        if skipped:
            print(f"   Skipped agents: {', '.join(skipped)}")
        
        # Dry run check
        if self.dry_run:
            print(f"\n🔍 DRY RUN - No changes made to DynamoDB")
            return
        
        # Write to DynamoDB
        if not items_to_write:
            print(f"\n✅ No policies to write")
            return
        
        print(f"\n💾 Writing to DynamoDB...")
        
        try:
            # Batch write (up to 25 items at a time)
            with self.table.batch_writer() as batch:
                for item in items_to_write:
                    batch.put_item(Item=item)
            
            print(f"✅ Successfully wrote {len(items_to_write)} policies to DynamoDB")
            
        except ClientError as e:
            print(f"❌ Error writing to DynamoDB: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            sys.exit(1)
    
    def delete_all_policies(self) -> None:
        """Delete all policies from DynamoDB (dangerous!)"""
        if self.dry_run:
            print(f"🔍 DRY RUN - Would delete all policies")
            return
        
        print(f"⚠️  WARNING: This will delete ALL policies from {POLICIES_TABLE}")
        print(f"⚠️  This action cannot be undone!")
        
        confirm = input(f"\nType 'DELETE ALL' to confirm: ")
        if confirm != 'DELETE ALL':
            print(f"❌ Deletion cancelled")
            return
        
        try:
            # Scan all items
            response = self.table.scan()
            items = response.get('Items', [])
            
            if not items:
                print(f"✅ No policies to delete")
                return
            
            print(f"\n🗑️  Deleting {len(items)} policies...")
            
            # Batch delete
            with self.table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={'policy_id': item['policy_id']})
            
            print(f"✅ Successfully deleted {len(items)} policies")
            
        except ClientError as e:
            print(f"❌ Error deleting policies: {e}")
            sys.exit(1)
    
    def verify_table_exists(self) -> bool:
        """Verify DynamoDB table exists"""
        try:
            self.table.load()
            print(f"✅ Table '{POLICIES_TABLE}' exists\n")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"❌ Error: Table '{POLICIES_TABLE}' not found")
                print(f"   Please deploy infrastructure first (Workstream 1)")
                return False
            raise


def main():
    parser = argparse.ArgumentParser(
        description='Seed agent policies from YAML into DynamoDB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load policies (skip existing)
  python scripts/seed_policies.py
  
  # Preview changes without writing
  python scripts/seed_policies.py --dry-run
  
  # Overwrite existing policies
  python scripts/seed_policies.py --force
  
  # Use different AWS profile
  python scripts/seed_policies.py --profile prod
  
  # Delete all policies (dangerous!)
  python scripts/seed_policies.py --delete-all
        """
    )
    
    parser.add_argument(
        '--profile',
        default=DEFAULT_PROFILE,
        help=f'AWS profile to use (default: {DEFAULT_PROFILE})'
    )
    
    parser.add_argument(
        '--region',
        default=DEFAULT_REGION,
        help=f'AWS region (default: {DEFAULT_REGION})'
    )
    
    parser.add_argument(
        '--config',
        default=CONFIG_FILE,
        help=f'Path to policies YAML file (default: {CONFIG_FILE})'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing to DynamoDB'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing policies'
    )
    
    parser.add_argument(
        '--delete-all',
        action='store_true',
        help='Delete all policies (requires confirmation)'
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("🔐 Sentra Policy Seeding Script")
    print("=" * 70)
    print()
    
    # Initialize seeder
    seeder = PolicySeeder(
        profile=args.profile,
        region=args.region,
        dry_run=args.dry_run
    )
    
    # Verify table exists
    if not seeder.verify_table_exists():
        sys.exit(1)
    
    # Delete all (if requested)
    if args.delete_all:
        seeder.delete_all_policies()
        return
    
    # Load and seed policies
    policies = seeder.load_policies_from_yaml(args.config)
    seeder.seed_policies(policies, force=args.force)
    
    print()
    print("=" * 70)
    print("✅ Policy seeding complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()
