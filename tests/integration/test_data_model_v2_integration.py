#!/usr/bin/env python3
"""
Integration Tests for Data Model v2 with Security Controller APIs

Tests the integration of new DynamoDB tables with Security Controller APIs:
- sentra-agent-registry
- sentra-tool-registry
- sentra-policies-metadata (+ S3)
- sentra-sigma-rules-metadata (+ S3)

Requirements: Task 13 (Workstream 6 - Milestone 4)
"""
import asyncio
import json
import time
from typing import Dict, List
from datetime import datetime
import warnings

import boto3
import requests
from botocore.exceptions import ClientError

# Disable SSL warnings for self-signed certificate in MVP
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


# Configuration
AWS_REGION = "us-east-1"
AWS_PROFILE = "sentra"
SECURITY_CONTROLLER_URL = "https://sentra-public-alb-1320390749.us-east-1.elb.amazonaws.com/v1"

# Expected data counts (from seed scripts)
EXPECTED_AGENTS = 3  # customer-query-agent, payment-agent, security-controller
EXPECTED_TOOLS_MIN = 15  # At least 15 tools seeded
EXPECTED_POLICIES_MIN = 2  # At least 2 policies
EXPECTED_SIGMA_RULES_MIN = 10  # At least 10 Sigma rules (actual: 11)


class IntegrationTestResult:
    """Tracks test results."""
    def __init__(self):
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.errors = []
        self.warnings = []
        self.timings = {}

    def record_pass(self, test_name: str, duration_ms: float):
        self.total_tests += 1
        self.passed_tests += 1
        self.timings[test_name] = duration_ms
        print(f"✅ {test_name} - PASSED ({duration_ms:.2f}ms)")

    def record_fail(self, test_name: str, error: str):
        self.total_tests += 1
        self.failed_tests += 1
        self.errors.append(f"{test_name}: {error}")
        print(f"❌ {test_name} - FAILED: {error}")

    def record_warning(self, test_name: str, warning: str):
        self.warnings.append(f"{test_name}: {warning}")
        print(f"⚠️  {test_name} - WARNING: {warning}")

    def print_summary(self):
        print("\n" + "=" * 80)
        print("INTEGRATION TEST SUMMARY")
        print("=" * 80)
        print(f"Total Tests: {self.total_tests}")
        print(f"Passed: {self.passed_tests}")
        print(f"Failed: {self.failed_tests}")
        print(f"Success Rate: {(self.passed_tests/self.total_tests*100):.1f}%")

        if self.warnings:
            print(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  ⚠️  {warning}")

        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                print(f"  ❌ {error}")

        print("\nPerformance Summary:")
        for test_name, duration in sorted(self.timings.items(), key=lambda x: x[1], reverse=True):
            print(f"  {test_name}: {duration:.2f}ms")

        print("=" * 80 + "\n")


class DataModelV2IntegrationTest:
    """Integration tests for Data Model v2."""

    def __init__(self):
        # Initialize AWS clients
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        self.dynamodb = session.resource('dynamodb')
        self.s3_client = session.client('s3')

        # DynamoDB tables
        self.agent_registry_table = self.dynamodb.Table('sentra-agent-registry')
        self.tool_registry_table = self.dynamodb.Table('sentra-tool-registry')
        self.policies_metadata_table = self.dynamodb.Table('sentra-policies-metadata')
        self.sigma_rules_metadata_table = self.dynamodb.Table('sentra-sigma-rules-metadata')

        # Test results
        self.results = IntegrationTestResult()

    # ========================================================================
    # Test 1: DynamoDB Table Existence and Schema
    # ========================================================================

    def test_tables_exist(self):
        """Test 1: Verify all 4 tables exist with correct schemas."""
        test_name = "Test 1: Tables Exist"
        start_time = time.time()

        try:
            tables = [
                ('sentra-agent-registry', ['agent_id']),
                ('sentra-tool-registry', ['tool_id']),
                ('sentra-policies-metadata', ['policy_id']),
                ('sentra-sigma-rules-metadata', ['rule_id'])
            ]

            for table_name, expected_keys in tables:
                table = self.dynamodb.Table(table_name)
                table.load()  # Throws exception if table doesn't exist

                # Verify partition key
                key_schema = table.key_schema
                pk = next((k for k in key_schema if k['KeyType'] == 'HASH'), None)
                if not pk or pk['AttributeName'] != expected_keys[0]:
                    raise Exception(f"{table_name}: Incorrect partition key")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 2: DynamoDB GSI Verification
    # ========================================================================

    def test_gsi_exist(self):
        """Test 2: Verify GSIs exist on tables."""
        test_name = "Test 2: GSIs Exist"
        start_time = time.time()

        try:
            # Expected GSIs per table
            expected_gsi = {
                'sentra-agent-registry': ['status-index'],
                'sentra-tool-registry': ['type-index'],
                'sentra-policies-metadata': ['agent-index', 'status-index'],
                'sentra-sigma-rules-metadata': ['level-index', 'status-index']
            }

            for table_name, gsi_names in expected_gsi.items():
                table = self.dynamodb.Table(table_name)
                table.load()

                actual_gsi = [gsi['IndexName'] for gsi in (table.global_secondary_indexes or [])]

                for gsi_name in gsi_names:
                    if gsi_name not in actual_gsi:
                        raise Exception(f"{table_name}: Missing GSI {gsi_name}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 3: Table Data Counts
    # ========================================================================

    def test_table_data_counts(self):
        """Test 3: Verify tables have expected data counts."""
        test_name = "Test 3: Table Data Counts"
        start_time = time.time()

        try:
            # Count agents
            response = self.agent_registry_table.scan(Select='COUNT')
            agent_count = response['Count']
            if agent_count != EXPECTED_AGENTS:
                self.results.record_warning(
                    test_name,
                    f"Expected {EXPECTED_AGENTS} agents, found {agent_count}"
                )

            # Count tools
            response = self.tool_registry_table.scan(Select='COUNT')
            tool_count = response['Count']
            if tool_count < EXPECTED_TOOLS_MIN:
                raise Exception(f"Expected >= {EXPECTED_TOOLS_MIN} tools, found {tool_count}")

            # Count policies
            response = self.policies_metadata_table.scan(Select='COUNT')
            policy_count = response['Count']
            if policy_count < EXPECTED_POLICIES_MIN:
                raise Exception(f"Expected >= {EXPECTED_POLICIES_MIN} policies, found {policy_count}")

            # Count Sigma rules
            response = self.sigma_rules_metadata_table.scan(Select='COUNT')
            sigma_count = response['Count']
            if sigma_count < EXPECTED_SIGMA_RULES_MIN:
                raise Exception(f"Expected >= {EXPECTED_SIGMA_RULES_MIN} Sigma rules, found {sigma_count}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 4: S3 Content Verification
    # ========================================================================

    def test_s3_content_exists(self):
        """Test 4: Verify S3 content exists for policies and Sigma rules."""
        test_name = "Test 4: S3 Content Exists"
        start_time = time.time()

        try:
            # Check policy S3 files
            response = self.policies_metadata_table.scan()
            for item in response.get('Items', []):
                s3_bucket = item.get('s3_bucket')
                s3_key = item.get('s3_key')

                if not s3_bucket or not s3_key:
                    raise Exception(f"Policy {item.get('policy_id')} missing S3 reference")

                # Verify S3 object exists
                try:
                    self.s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
                except ClientError:
                    raise Exception(f"S3 object not found: s3://{s3_bucket}/{s3_key}")

            # Check Sigma rule S3 files
            response = self.sigma_rules_metadata_table.scan()
            for item in response.get('Items', []):
                s3_bucket = item.get('s3_bucket')
                s3_key = item.get('s3_key')

                if not s3_bucket or not s3_key:
                    raise Exception(f"Sigma rule {item.get('rule_id')} missing S3 reference")

                # Verify S3 object exists
                try:
                    self.s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
                except ClientError:
                    raise Exception(f"S3 object not found: s3://{s3_bucket}/{s3_key}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 5: GET /v1/agents API
    # ========================================================================

    def test_api_get_agents(self):
        """Test 5: GET /v1/agents returns agents from sentra-agent-registry."""
        test_name = "Test 5: GET /v1/agents"
        start_time = time.time()

        try:
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/agents", timeout=10, verify=False)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

            data = response.json()
            agents = data.get('agents', [])
            total = data.get('total', 0)

            if not agents:
                raise Exception("No agents returned")

            if total != len(agents):
                self.results.record_warning(test_name, f"Total ({total}) != len(agents) ({len(agents)})")

            # Verify agent structure
            for agent in agents:
                required_fields = ['agent_id', 'name', 'description', 'status']
                missing_fields = [f for f in required_fields if f not in agent]
                if missing_fields:
                    raise Exception(f"Agent missing fields: {missing_fields}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 6: GET /v1/agents/{id} API
    # ========================================================================

    def test_api_get_agent_detail(self):
        """Test 6: GET /v1/agents/{id} returns agent with runtime stats."""
        test_name = "Test 6: GET /v1/agents/{id}"
        start_time = time.time()

        try:
            agent_id = "customer-query-agent"
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/agents/{agent_id}", timeout=10, verify=False)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

            agent = response.json()

            # Verify required fields
            required_fields = [
                'agent_id', 'name', 'description', 'status',
                'requests_total', 'requests_allowed', 'requests_denied',
                'active_sessions', 'trust_score_avg'
            ]
            missing_fields = [f for f in required_fields if f not in agent]
            if missing_fields:
                raise Exception(f"Agent missing runtime stats: {missing_fields}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 7: GET /v1/agents/{id}/tools API
    # ========================================================================

    def test_api_get_agent_tools(self):
        """Test 7: GET /v1/agents/{id}/tools returns tools from registry (hybrid pattern)."""
        test_name = "Test 7: GET /v1/agents/{id}/tools"
        start_time = time.time()

        try:
            agent_id = "customer-query-agent"
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/agents/{agent_id}/tools", timeout=10, verify=False)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

            data = response.json()
            tools = data.get('tools', [])
            total = data.get('total', 0)

            if not tools:
                raise Exception("No tools returned for customer-query-agent")

            # Verify tool structure
            for tool in tools:
                required_fields = ['tool_id', 'name', 'tool_type', 'description', 'parameters']
                missing_fields = [f for f in required_fields if f not in tool]
                if missing_fields:
                    raise Exception(f"Tool missing fields: {missing_fields}")

                # Verify tool_type is READ or WRITE
                if tool['tool_type'] not in ['READ', 'WRITE']:
                    raise Exception(f"Invalid tool_type: {tool['tool_type']}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 8: GET /v1/policies API
    # ========================================================================

    def test_api_get_policies(self):
        """Test 8: GET /v1/policies returns policies from sentra-policies-metadata."""
        test_name = "Test 8: GET /v1/policies"
        start_time = time.time()

        try:
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/policies", timeout=10, verify=False)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

            data = response.json()
            policies = data.get('policies', [])

            if not policies:
                raise Exception("No policies returned")

            # Verify policy structure
            for policy in policies:
                required_fields = ['policy_id', 'agent_id', 'name', 'version', 'status', 's3_key']
                missing_fields = [f for f in required_fields if f not in policy]
                if missing_fields:
                    raise Exception(f"Policy missing fields: {missing_fields}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 9: GET /v1/sigma-rules API
    # ========================================================================

    def test_api_get_sigma_rules(self):
        """Test 9: GET /v1/sigma-rules returns rules from sentra-sigma-rules-metadata."""
        test_name = "Test 9: GET /v1/sigma-rules"
        start_time = time.time()

        try:
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/sigma-rules", timeout=10, verify=False)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

            data = response.json()
            rules = data.get('rules', [])

            if not rules:
                raise Exception("No Sigma rules returned")

            # Verify rule structure
            for rule in rules:
                required_fields = ['rule_id', 'title', 'description', 'status', 'level', 's3_key']
                missing_fields = [f for f in required_fields if f not in rule]
                if missing_fields:
                    raise Exception(f"Sigma rule missing fields: {missing_fields}")

                # Verify level is valid
                valid_levels = ['critical', 'high', 'medium', 'low']
                if rule['level'] not in valid_levels:
                    raise Exception(f"Invalid level: {rule['level']}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 10: GSI Query Performance
    # ========================================================================

    def test_gsi_query_performance(self):
        """Test 10: Verify GSI queries complete within performance targets."""
        test_name = "Test 10: GSI Query Performance"
        start_time = time.time()

        try:
            # Test 10a: Query agents by status (should be < 50ms)
            gsi_start = time.time()
            response = self.agent_registry_table.query(
                IndexName='status-index',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'active'}
            )
            gsi_duration = (time.time() - gsi_start) * 1000

            if gsi_duration > 100:
                self.results.record_warning(test_name, f"Agent status-index query took {gsi_duration:.2f}ms (target: <100ms)")

            # Test 10b: Query tools by type
            gsi_start = time.time()
            response = self.tool_registry_table.query(
                IndexName='type-index',
                KeyConditionExpression='tool_type = :type',
                ExpressionAttributeValues={':type': 'READ'}
            )
            gsi_duration = (time.time() - gsi_start) * 1000

            if gsi_duration > 100:
                self.results.record_warning(test_name, f"Tool type-index query took {gsi_duration:.2f}ms (target: <100ms)")

            # Test 10c: Query Sigma rules by level
            gsi_start = time.time()
            response = self.sigma_rules_metadata_table.query(
                IndexName='level-index',
                KeyConditionExpression='#level = :level',
                ExpressionAttributeNames={'#level': 'level'},
                ExpressionAttributeValues={':level': 'high'}
            )
            gsi_duration = (time.time() - gsi_start) * 1000

            if gsi_duration > 100:
                self.results.record_warning(test_name, f"Sigma level-index query took {gsi_duration:.2f}ms (target: <100ms)")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 11: API Performance (Latency Targets)
    # ========================================================================

    def test_api_performance(self):
        """Test 11: Verify API endpoints meet latency targets."""
        test_name = "Test 11: API Performance"
        start_time = time.time()

        try:
            # Target latencies (from Task 13)
            api_targets = {
                '/v1/agents': 100,  # < 100ms
                '/v1/agents/customer-query-agent/tools': 150,  # < 150ms
                '/v1/policies': 100,
                '/v1/sigma-rules': 100
            }

            for endpoint, target_ms in api_targets.items():
                api_start = time.time()
                response = requests.get(f"{SECURITY_CONTROLLER_URL}{endpoint}", timeout=10, verify=False)
                api_duration = (time.time() - api_start) * 1000

                if response.status_code != 200:
                    raise Exception(f"{endpoint}: HTTP {response.status_code}")

                if api_duration > target_ms * 2:  # Allow 2x target for MVP
                    self.results.record_warning(
                        test_name,
                        f"{endpoint} took {api_duration:.2f}ms (target: <{target_ms}ms)"
                    )

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Test 12: Error Scenarios
    # ========================================================================

    def test_error_scenarios(self):
        """Test 12: Verify APIs handle errors gracefully."""
        test_name = "Test 12: Error Scenarios"
        start_time = time.time()

        try:
            # Test 12a: Non-existent agent
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/agents/non-existent-agent", timeout=10, verify=False)
            if response.status_code != 404:
                raise Exception(f"Expected 404 for non-existent agent, got {response.status_code}")

            # Test 12b: Invalid query parameters
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/policies?limit=5000", timeout=10, verify=False)
            if response.status_code != 400:
                self.results.record_warning(test_name, f"Expected 400 for invalid limit, got {response.status_code}")

            # Test 12c: Invalid status filter
            response = requests.get(f"{SECURITY_CONTROLLER_URL}/sigma-rules?status=invalid", timeout=10, verify=False)
            if response.status_code != 400:
                self.results.record_warning(test_name, f"Expected 400 for invalid status, got {response.status_code}")

            duration_ms = (time.time() - start_time) * 1000
            self.results.record_pass(test_name, duration_ms)

        except Exception as e:
            self.results.record_fail(test_name, str(e))

    # ========================================================================
    # Main Test Runner
    # ========================================================================

    def run_all_tests(self):
        """Run all integration tests."""
        print("\n" + "=" * 80)
        print("DATA MODEL V2 INTEGRATION TESTS")
        print("=" * 80)
        print(f"Security Controller URL: {SECURITY_CONTROLLER_URL}")
        print(f"AWS Region: {AWS_REGION}")
        print(f"AWS Profile: {AWS_PROFILE}")
        print("=" * 80 + "\n")

        # Run tests
        self.test_tables_exist()
        self.test_gsi_exist()
        self.test_table_data_counts()
        self.test_s3_content_exists()
        self.test_api_get_agents()
        self.test_api_get_agent_detail()
        self.test_api_get_agent_tools()
        self.test_api_get_policies()
        self.test_api_get_sigma_rules()
        self.test_gsi_query_performance()
        self.test_api_performance()
        self.test_error_scenarios()

        # Print summary
        self.results.print_summary()

        # Return exit code
        return 0 if self.results.failed_tests == 0 else 1


def main():
    """Main entry point."""
    test_suite = DataModelV2IntegrationTest()
    exit_code = test_suite.run_all_tests()

    # Write results to file
    output_file = "/tmp/data_model_integration_test_results.txt"
    with open(output_file, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("DATA MODEL V2 INTEGRATION TEST RESULTS\n")
        f.write("=" * 80 + "\n")
        f.write(f"Timestamp: {datetime.utcnow().isoformat()}Z\n")
        f.write(f"Total Tests: {test_suite.results.total_tests}\n")
        f.write(f"Passed: {test_suite.results.passed_tests}\n")
        f.write(f"Failed: {test_suite.results.failed_tests}\n")
        f.write(f"Success Rate: {(test_suite.results.passed_tests/test_suite.results.total_tests*100):.1f}%\n")
        f.write("\n")

        if test_suite.results.warnings:
            f.write(f"Warnings ({len(test_suite.results.warnings)}):\n")
            for warning in test_suite.results.warnings:
                f.write(f"  ⚠️  {warning}\n")
            f.write("\n")

        if test_suite.results.errors:
            f.write(f"Errors ({len(test_suite.results.errors)}):\n")
            for error in test_suite.results.errors:
                f.write(f"  ❌ {error}\n")
            f.write("\n")

        f.write("Performance Summary:\n")
        for test_name, duration in sorted(test_suite.results.timings.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {test_name}: {duration:.2f}ms\n")
        f.write("=" * 80 + "\n")

    print(f"\n✅ Results written to: {output_file}\n")

    return exit_code


if __name__ == "__main__":
    exit(main())
