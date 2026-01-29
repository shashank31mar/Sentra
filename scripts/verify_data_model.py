#!/usr/bin/env python3
"""
Comprehensive verification script for Sentra Data Model v2.
Verifies all tables, GSIs, data integrity, and S3 content.
"""
import boto3
import sys
from typing import Dict, List, Tuple
from botocore.exceptions import ClientError

from schemas import (
    Agent,
    Tool,
    PolicyMetadata,
    SigmaRuleMetadata,
)
from query_helpers import (
    list_agents,
    list_all_tools,
    list_policies_by_status,
    list_all_sigma_rules,
    get_policy_full,
    get_sigma_rule_full,
)


# AWS clients
dynamodb = boto3.client('dynamodb', region_name='us-east-1')
s3_client = boto3.client('s3', region_name='us-east-1')


class VerificationReport:
    """Tracks verification results."""
    
    def __init__(self):
        self.checks = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0
    
    def add_pass(self, check_name: str, message: str = ""):
        """Add a passing check."""
        self.checks.append(("PASS", check_name, message))
        self.passed += 1
        print(f"✅ PASS: {check_name}")
        if message:
            print(f"   {message}")
    
    def add_fail(self, check_name: str, message: str):
        """Add a failing check."""
        self.checks.append(("FAIL", check_name, message))
        self.failed += 1
        print(f"❌ FAIL: {check_name}")
        print(f"   {message}")
    
    def add_warning(self, check_name: str, message: str):
        """Add a warning."""
        self.checks.append(("WARN", check_name, message))
        self.warnings += 1
        print(f"⚠️  WARN: {check_name}")
        print(f"   {message}")
    
    def generate_report(self) -> str:
        """Generate final report text."""
        report = []
        report.append("=" * 80)
        report.append("SENTRA DATA MODEL V2 - VERIFICATION REPORT")
        report.append("=" * 80)
        report.append("")
        report.append(f"Total Checks: {len(self.checks)}")
        report.append(f"✅ Passed: {self.passed}")
        report.append(f"❌ Failed: {self.failed}")
        report.append(f"⚠️  Warnings: {self.warnings}")
        report.append("")
        report.append("=" * 80)
        report.append("DETAILED RESULTS")
        report.append("=" * 80)
        report.append("")
        
        for status, check_name, message in self.checks:
            icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
            report.append(f"{icon} {status}: {check_name}")
            if message:
                report.append(f"   {message}")
            report.append("")
        
        report.append("=" * 80)
        if self.failed == 0:
            report.append("✅ ALL CHECKS PASSED")
        else:
            report.append(f"❌ {self.failed} CHECK(S) FAILED")
        report.append("=" * 80)
        
        return "\n".join(report)


def verify_table_exists(table_name: str, report: VerificationReport) -> bool:
    """Verify a DynamoDB table exists."""
    try:
        response = dynamodb.describe_table(TableName=table_name)
        status = response['Table']['TableStatus']
        
        if status == 'ACTIVE':
            report.add_pass(
                f"Table Exists: {table_name}",
                f"Status: {status}"
            )
            return True
        else:
            report.add_warning(
                f"Table Exists: {table_name}",
                f"Status: {status} (not ACTIVE)"
            )
            return False
            
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            report.add_fail(
                f"Table Exists: {table_name}",
                "Table does not exist"
            )
        else:
            report.add_fail(
                f"Table Exists: {table_name}",
                f"Error: {str(e)}"
            )
        return False


def verify_gsi_exists(table_name: str, gsi_name: str, report: VerificationReport) -> bool:
    """Verify a GSI exists on a table."""
    try:
        response = dynamodb.describe_table(TableName=table_name)
        gsis = response['Table'].get('GlobalSecondaryIndexes', [])
        
        for gsi in gsis:
            if gsi['IndexName'] == gsi_name:
                status = gsi['IndexStatus']
                if status == 'ACTIVE':
                    report.add_pass(
                        f"GSI Exists: {table_name}.{gsi_name}",
                        f"Status: {status}"
                    )
                    return True
                else:
                    report.add_warning(
                        f"GSI Exists: {table_name}.{gsi_name}",
                        f"Status: {status} (not ACTIVE)"
                    )
                    return False
        
        report.add_fail(
            f"GSI Exists: {table_name}.{gsi_name}",
            "GSI not found"
        )
        return False
        
    except ClientError as e:
        report.add_fail(
            f"GSI Exists: {table_name}.{gsi_name}",
            f"Error: {str(e)}"
        )
        return False


def verify_item_count(table_name: str, expected_min: int, expected_max: int, report: VerificationReport) -> int:
    """Verify table has expected number of items."""
    try:
        response = dynamodb.scan(
            TableName=table_name,
            Select='COUNT'
        )
        count = response['Count']
        
        if expected_min <= count <= expected_max:
            report.add_pass(
                f"Item Count: {table_name}",
                f"Count: {count} (expected {expected_min}-{expected_max})"
            )
        elif count < expected_min:
            report.add_fail(
                f"Item Count: {table_name}",
                f"Count: {count} (expected at least {expected_min})"
            )
        else:
            report.add_warning(
                f"Item Count: {table_name}",
                f"Count: {count} (expected max {expected_max})"
            )
        
        return count
        
    except ClientError as e:
        report.add_fail(
            f"Item Count: {table_name}",
            f"Error: {str(e)}"
        )
        return 0


def verify_s3_files_exist(report: VerificationReport) -> Tuple[int, int]:
    """Verify S3 files exist for all policy and Sigma rule metadata."""
    missing_files = []
    found_files = 0
    
    try:
        # Check policy files
        policies = list_policies_by_status('active')
        for policy in policies:
            try:
                s3_client.head_object(
                    Bucket=policy.s3_bucket,
                    Key=policy.s3_key
                )
                found_files += 1
            except ClientError:
                missing_files.append(f"Policy: {policy.s3_bucket}/{policy.s3_key}")
        
        # Check Sigma rule files
        rules = list_all_sigma_rules()
        for rule in rules:
            try:
                s3_client.head_object(
                    Bucket=rule.s3_bucket,
                    Key=rule.s3_key
                )
                found_files += 1
            except ClientError:
                missing_files.append(f"Sigma Rule: {rule.s3_bucket}/{rule.s3_key}")
        
        if not missing_files:
            report.add_pass(
                "S3 Files Exist",
                f"All {found_files} S3 files found"
            )
        else:
            report.add_fail(
                "S3 Files Exist",
                f"Missing {len(missing_files)} files:\n   " + "\n   ".join(missing_files)
            )
        
        return found_files, len(missing_files)
        
    except Exception as e:
        report.add_fail(
            "S3 Files Exist",
            f"Error checking S3 files: {str(e)}"
        )
        return 0, 0


def verify_data_integrity(report: VerificationReport):
    """Verify data integrity across tables."""
    try:
        # Get all agents
        agents = list_agents()
        agent_ids = {agent.agent_id for agent in agents}
        
        # Get all policies
        policies = list_policies_by_status('active')
        
        # Check that all policy agent_ids exist in agent registry
        invalid_agent_refs = []
        for policy in policies:
            if policy.agent_id not in agent_ids:
                invalid_agent_refs.append(f"{policy.policy_id} -> {policy.agent_id}")
        
        if not invalid_agent_refs:
            report.add_pass(
                "Data Integrity: Policy -> Agent References",
                f"All {len(policies)} policies reference valid agents"
            )
        else:
            report.add_fail(
                "Data Integrity: Policy -> Agent References",
                f"Invalid references:\n   " + "\n   ".join(invalid_agent_refs)
            )
        
        # Get all tools
        tools = list_all_tools()
        tool_ids = {tool.tool_id for tool in tools}
        
        # Check that all allowed_tools in policies exist in tool registry
        invalid_tool_refs = []
        for policy in policies:
            try:
                full_policy = get_policy_full(policy.policy_id)
                for tool_id in full_policy.allowed_tools:
                    if tool_id not in tool_ids:
                        invalid_tool_refs.append(f"{policy.policy_id} -> {tool_id}")
            except Exception as e:
                report.add_warning(
                    f"Data Integrity: Policy {policy.policy_id}",
                    f"Could not load full policy: {str(e)}"
                )
        
        if not invalid_tool_refs:
            report.add_pass(
                "Data Integrity: Policy -> Tool References",
                "All policy tool references are valid"
            )
        else:
            report.add_fail(
                "Data Integrity: Policy -> Tool References",
                f"Invalid references:\n   " + "\n   ".join(invalid_tool_refs)
            )
        
    except Exception as e:
        report.add_fail(
            "Data Integrity Check",
            f"Error: {str(e)}"
        )


def verify_pydantic_validation(report: VerificationReport):
    """Verify all data validates with Pydantic schemas."""
    errors = []
    
    try:
        # Validate agents
        agents = list_agents()
        report.add_pass(
            "Pydantic Validation: Agents",
            f"All {len(agents)} agents validated"
        )
    except Exception as e:
        errors.append(f"Agents: {str(e)}")
    
    try:
        # Validate tools
        tools = list_all_tools()
        report.add_pass(
            "Pydantic Validation: Tools",
            f"All {len(tools)} tools validated"
        )
    except Exception as e:
        errors.append(f"Tools: {str(e)}")
    
    try:
        # Validate policy metadata
        policies = list_policies_by_status('active')
        report.add_pass(
            "Pydantic Validation: Policy Metadata",
            f"All {len(policies)} policy metadata items validated"
        )
    except Exception as e:
        errors.append(f"Policy Metadata: {str(e)}")
    
    try:
        # Validate Sigma rule metadata
        rules = list_all_sigma_rules()
        report.add_pass(
            "Pydantic Validation: Sigma Rule Metadata",
            f"All {len(rules)} Sigma rule metadata items validated"
        )
    except Exception as e:
        errors.append(f"Sigma Rule Metadata: {str(e)}")
    
    if errors:
        report.add_fail(
            "Pydantic Validation",
            "Validation errors:\n   " + "\n   ".join(errors)
        )


def verify_query_patterns(report: VerificationReport):
    """Verify query patterns work correctly."""
    try:
        # Test agent queries
        agents = list_agents()
        active_agents = list_agents(status='active')
        
        if len(active_agents) <= len(agents):
            report.add_pass(
                "Query Pattern: list_agents(status='active')",
                f"Returned {len(active_agents)} of {len(agents)} agents"
            )
        else:
            report.add_fail(
                "Query Pattern: list_agents(status='active')",
                f"Returned more active agents ({len(active_agents)}) than total ({len(agents)})"
            )
        
        # Test tool queries
        from query_helpers import list_tools_by_type
        read_tools = list_tools_by_type('READ')
        write_tools = list_tools_by_type('WRITE')
        all_tools = list_all_tools()
        
        if len(read_tools) + len(write_tools) == len(all_tools):
            report.add_pass(
                "Query Pattern: list_tools_by_type()",
                f"READ: {len(read_tools)}, WRITE: {len(write_tools)}, Total: {len(all_tools)}"
            )
        else:
            report.add_warning(
                "Query Pattern: list_tools_by_type()",
                f"READ ({len(read_tools)}) + WRITE ({len(write_tools)}) != Total ({len(all_tools)})"
            )
        
        # Test policy queries
        from query_helpers import list_policies_by_agent
        if agents:
            agent_id = agents[0].agent_id
            agent_policies = list_policies_by_agent(agent_id)
            report.add_pass(
                f"Query Pattern: list_policies_by_agent('{agent_id}')",
                f"Returned {len(agent_policies)} policies"
            )
        
        # Test Sigma rule queries
        from query_helpers import list_sigma_rules_by_level
        critical_rules = list_sigma_rules_by_level('critical')
        high_rules = list_sigma_rules_by_level('high')
        report.add_pass(
            "Query Pattern: list_sigma_rules_by_level()",
            f"Critical: {len(critical_rules)}, High: {len(high_rules)}"
        )
        
    except Exception as e:
        report.add_fail(
            "Query Pattern Verification",
            f"Error: {str(e)}"
        )


def verify_s3_content_loading(report: VerificationReport):
    """Verify S3 content can be loaded and parsed."""
    errors = []
    success_count = 0
    
    try:
        # Test policy loading
        policies = list_policies_by_status('active')
        for policy in policies[:2]:  # Test first 2 policies
            try:
                full_policy = get_policy_full(policy.policy_id)
                if full_policy.allowed_tools and full_policy.policies:
                    success_count += 1
                else:
                    errors.append(f"Policy {policy.policy_id}: Missing allowed_tools or policies")
            except Exception as e:
                errors.append(f"Policy {policy.policy_id}: {str(e)}")
        
        # Test Sigma rule loading
        rules = list_all_sigma_rules()
        for rule in rules[:2]:  # Test first 2 rules
            try:
                full_rule = get_sigma_rule_full(rule.rule_id)
                if full_rule.detection and full_rule.level:
                    success_count += 1
                else:
                    errors.append(f"Rule {rule.rule_id}: Missing detection or level")
            except Exception as e:
                errors.append(f"Rule {rule.rule_id}: {str(e)}")
        
        if not errors:
            report.add_pass(
                "S3 Content Loading",
                f"Successfully loaded and parsed {success_count} S3 documents"
            )
        else:
            report.add_fail(
                "S3 Content Loading",
                f"Errors loading S3 content:\n   " + "\n   ".join(errors)
            )
        
    except Exception as e:
        report.add_fail(
            "S3 Content Loading",
            f"Error: {str(e)}"
        )


def main():
    """Run all verification checks."""
    print("=" * 80)
    print("SENTRA DATA MODEL V2 - VERIFICATION")
    print("=" * 80)
    print()
    
    report = VerificationReport()
    
    # Check 1: Verify all tables exist
    print("\n" + "=" * 80)
    print("CHECK 1: Table Existence")
    print("=" * 80)
    verify_table_exists('sentra-agent-registry', report)
    verify_table_exists('sentra-tool-registry', report)
    verify_table_exists('sentra-policies-metadata', report)
    verify_table_exists('sentra-sigma-rules-metadata', report)
    
    # Check 2: Verify all GSIs exist
    print("\n" + "=" * 80)
    print("CHECK 2: GSI Existence")
    print("=" * 80)
    verify_gsi_exists('sentra-agent-registry', 'status-index', report)
    verify_gsi_exists('sentra-tool-registry', 'type-index', report)
    verify_gsi_exists('sentra-policies-metadata', 'agent-index', report)
    verify_gsi_exists('sentra-policies-metadata', 'status-index', report)
    verify_gsi_exists('sentra-sigma-rules-metadata', 'level-index', report)
    verify_gsi_exists('sentra-sigma-rules-metadata', 'status-index', report)
    
    # Check 3: Verify item counts
    print("\n" + "=" * 80)
    print("CHECK 3: Item Counts")
    print("=" * 80)
    verify_item_count('sentra-agent-registry', 2, 10, report)
    verify_item_count('sentra-tool-registry', 10, 50, report)
    verify_item_count('sentra-policies-metadata', 2, 10, report)
    verify_item_count('sentra-sigma-rules-metadata', 5, 50, report)
    
    # Check 4: Verify S3 files exist
    print("\n" + "=" * 80)
    print("CHECK 4: S3 File Existence")
    print("=" * 80)
    verify_s3_files_exist(report)
    
    # Check 5: Verify data integrity
    print("\n" + "=" * 80)
    print("CHECK 5: Data Integrity")
    print("=" * 80)
    verify_data_integrity(report)
    
    # Check 6: Verify Pydantic validation
    print("\n" + "=" * 80)
    print("CHECK 6: Pydantic Validation")
    print("=" * 80)
    verify_pydantic_validation(report)
    
    # Check 7: Verify query patterns
    print("\n" + "=" * 80)
    print("CHECK 7: Query Patterns")
    print("=" * 80)
    verify_query_patterns(report)
    
    # Check 8: Verify S3 content loading
    print("\n" + "=" * 80)
    print("CHECK 8: S3 Content Loading")
    print("=" * 80)
    verify_s3_content_loading(report)
    
    # Generate final report
    print("\n")
    report_text = report.generate_report()
    print(report_text)
    
    # Write report to file
    report_path = '/tmp/data_model_verification_report.txt'
    with open(report_path, 'w') as f:
        f.write(report_text)
    
    print(f"\n📄 Full report written to: {report_path}")
    
    # Return exit code
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
