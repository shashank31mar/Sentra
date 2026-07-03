"""
End-to-End Integration Tests for Policy CRUD Operations

Tests complete flow: API → PolicyService → DynamoDB/S3 → Dashboard
Reference: Workstream 11 - Agent Policy CRUD

Requires:
- AWS credentials configured
- DynamoDB tables created
- S3 bucket exists
- Security Controller API running
"""

import pytest
import requests
import json
import time
from typing import Dict
import os


# Configuration
API_BASE_URL = os.getenv("SECURITY_CONTROLLER_URL", "http://localhost:8080")
OPERATOR_EMAIL = "test-integration@sentra.com"
TEST_AGENT_ID = "test-integration-agent"

# These are LIVE-SERVICE e2e tests: every case drives POST/GET/DELETE /v1/policies
# against a deployed (or locally-run) controller. Mark the whole module so a runner
# can `-m "not requires_services"` to exclude them, and mirror the codebase's
# skip-when-absent contract (test_post_cutover_suite.py:47) so an offline run SKIPs
# cleanly instead of hard-failing with a raw ConnectionError.
pytestmark = [pytest.mark.integration, pytest.mark.requires_services]

# Short connect+read timeout so an absent endpoint fails fast rather than hanging.
_HEALTH_TIMEOUT = float(os.environ.get("SENTRA_HEALTH_TIMEOUT", "10"))


@pytest.fixture(scope="session", autouse=True)
def _require_reachable():
    """One `GET /v1/health` probe per session. If the controller is unreachable
    (no deployed target from this env — e.g. nothing listening on :8080), skip the
    WHOLE suite cleanly rather than erroring, so the file is safe to collect/run
    anywhere (mirrors test_post_cutover_suite.py:_require_reachable).

    A reachable controller that returns a non-200 (e.g. 503 = a dependency is
    unhealthy) is NOT a skip — the suite should run and surface that as real
    failures; only an unreachable endpoint (connection refused / DNS / timeout)
    skips."""
    base_url = API_BASE_URL.rstrip("/")
    try:
        requests.get(f"{base_url}/v1/health", timeout=_HEALTH_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        pytest.skip(
            f"controller not reachable at {base_url} ({exc.__class__.__name__}); "
            "policy-CRUD e2e requires a running controller "
            "(set SECURITY_CONTROLLER_URL to the prod/staging ALB, or start it locally)."
        )


@pytest.fixture(scope="module")
def api_headers():
    """Common headers for API requests."""
    return {
        "Content-Type": "application/json",
        "X-Operator-Email": OPERATOR_EMAIL
    }


@pytest.fixture
def sample_policy_payload():
    """Sample policy payload for testing."""
    return {
        "schema_version": "v1",
        "agent_id": TEST_AGENT_ID,
        "name": "Integration Test Policy",
        "version": "1.0.0",
        "description": "Policy created by integration test",
        "allowed_tools": [
            "query_customers",
            "query_orders"
        ],
        "policies": [
            {
                "policy_id": "pol-int-001",
                "name": "Test Query Limit",
                "description": "Limit integration test queries",
                "rule": "query_limit <= 500",
                "action": "DENY",
                "severity": "high",
                "enabled": True
            },
            {
                "policy_id": "pol-int-002",
                "name": "Test Rate Limit",
                "description": "Rate limit for tests",
                "rule": "requests_per_minute <= 30",
                "action": "DENY",
                "severity": "medium",
                "enabled": True
            }
        ]
    }


@pytest.fixture(scope="function")
def cleanup_policy():
    """Fixture to cleanup policy after test."""
    policy_ids_to_cleanup = []

    yield policy_ids_to_cleanup

    # Cleanup
    for policy_id in policy_ids_to_cleanup:
        try:
            response = requests.delete(
                f"{API_BASE_URL}/v1/policies/{policy_id}",
                headers={"X-Operator-Email": OPERATOR_EMAIL}
            )
            print(f"Cleanup: Deleted policy {policy_id}, status: {response.status_code}")
        except Exception as e:
            print(f"Cleanup failed for {policy_id}: {e}")


class TestPolicyCRUDEndToEnd:
    """End-to-end tests for complete CRUD flow."""

    @pytest.mark.integration
    def test_create_policy_e2e(self, api_headers, sample_policy_payload, cleanup_policy):
        """Test end-to-end policy creation."""
        # Create policy
        response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers
        )

        # Assert creation success
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"

        data = response.json()
        assert data['success'] is True
        assert 'policy_id' in data
        assert data['version'] == "1.0.0"
        assert 's3_key' in data
        assert 's3_version_id' in data
        assert data['message'] == "Policy created successfully"

        policy_id = data['policy_id']
        cleanup_policy.append(policy_id)

        # Verify policy was created by fetching it
        time.sleep(1)  # Allow for eventual consistency

        get_response = requests.get(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            params={"include_content": True}
        )

        assert get_response.status_code == 200
        policy_data = get_response.json()
        assert policy_data['success'] is True
        assert policy_data['metadata']['policy_id'] == policy_id
        assert policy_data['content']['agent_id'] == TEST_AGENT_ID

    @pytest.mark.integration
    def test_update_policy_e2e(self, api_headers, sample_policy_payload, cleanup_policy):
        """Test end-to-end policy update."""
        # First create a policy
        create_response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers
        )
        assert create_response.status_code == 201

        policy_id = create_response.json()['policy_id']
        cleanup_policy.append(policy_id)

        time.sleep(1)

        # Update policy
        updated_payload = sample_policy_payload.copy()
        updated_payload['version'] = "1.1.0"
        updated_payload['description'] = "Updated by integration test"
        updated_payload['policies'].append({
            "policy_id": "pol-int-003",
            "name": "New Policy Rule",
            "description": "Added during update",
            "rule": "new_parameter < 100",
            "action": "DENY",
            "severity": "low",
            "enabled": True
        })

        update_response = requests.put(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            json=updated_payload,
            headers=api_headers
        )

        # Assert update success
        assert update_response.status_code == 200, f"Expected 200, got {update_response.status_code}: {update_response.text}"

        data = update_response.json()
        assert data['success'] is True
        assert data['version'] == "1.1.0"
        assert data['previous_version'] == "1.0.0"
        assert data['message'] == "Policy updated successfully"

        # Verify update by fetching
        time.sleep(1)

        get_response = requests.get(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            params={"include_content": True}
        )

        assert get_response.status_code == 200
        policy_data = get_response.json()
        assert policy_data['content']['version'] == "1.1.0"
        assert policy_data['content']['description'] == "Updated by integration test"
        assert len(policy_data['content']['policies']) == 3

    @pytest.mark.integration
    def test_delete_policy_e2e(self, api_headers, sample_policy_payload):
        """Test end-to-end policy deletion (soft delete)."""
        # Create policy
        create_response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers
        )
        assert create_response.status_code == 201

        policy_id = create_response.json()['policy_id']

        time.sleep(1)

        # Delete policy
        delete_response = requests.delete(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            headers=api_headers
        )

        # Assert deletion success
        assert delete_response.status_code == 200, f"Expected 200, got {delete_response.status_code}: {delete_response.text}"

        data = delete_response.json()
        assert data['success'] is True
        assert data['status'] == 'disabled'
        assert data['message'] == "Policy disabled successfully"

        # Verify policy is disabled (still fetchable but disabled)
        time.sleep(1)

        get_response = requests.get(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            params={"include_content": False}
        )

        if get_response.status_code == 200:
            policy_data = get_response.json()
            assert policy_data['metadata']['status'] == 'disabled'

    @pytest.mark.integration
    def test_full_crud_lifecycle(self, api_headers, sample_policy_payload):
        """Test complete CRUD lifecycle: Create → Read → Update → Delete."""
        # 1. CREATE
        create_response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers
        )
        assert create_response.status_code == 201
        policy_id = create_response.json()['policy_id']

        time.sleep(1)

        # 2. READ
        read_response = requests.get(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            params={"include_content": True}
        )
        assert read_response.status_code == 200
        assert read_response.json()['content']['version'] == "1.0.0"

        # 3. UPDATE
        updated_payload = sample_policy_payload.copy()
        updated_payload['version'] = "2.0.0"
        updated_payload['description'] = "Lifecycle test update"

        update_response = requests.put(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            json=updated_payload,
            headers=api_headers
        )
        assert update_response.status_code == 200
        assert update_response.json()['version'] == "2.0.0"

        time.sleep(1)

        # 4. READ UPDATED
        read_updated_response = requests.get(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            params={"include_content": True}
        )
        assert read_updated_response.status_code == 200
        assert read_updated_response.json()['content']['version'] == "2.0.0"
        assert read_updated_response.json()['content']['description'] == "Lifecycle test update"

        # 5. DELETE
        delete_response = requests.delete(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            headers=api_headers
        )
        assert delete_response.status_code == 200
        assert delete_response.json()['status'] == 'disabled'


class TestPolicyValidationE2E:
    """End-to-end tests for validation scenarios."""

    @pytest.mark.integration
    def test_create_invalid_policy_schema(self, api_headers):
        """Test creation with invalid schema."""
        invalid_payload = {
            "schema_version": "v1",
            "agent_id": "test-agent",
            # Missing required fields: name, version, allowed_tools, policies
        }

        response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=invalid_payload,
            headers=api_headers
        )

        # Should return 400 Bad Request
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'error' in data

    @pytest.mark.integration
    def test_create_duplicate_policy(self, api_headers, sample_policy_payload, cleanup_policy):
        """Test creating duplicate policy."""
        # Create first policy
        create_response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers
        )
        assert create_response.status_code == 201
        cleanup_policy.append(create_response.json()['policy_id'])

        time.sleep(1)

        # Try to create duplicate
        duplicate_response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers
        )

        # Should return 409 Conflict
        assert duplicate_response.status_code == 409
        data = duplicate_response.json()
        assert data['success'] is False
        assert 'already exists' in data['error'].lower()

    @pytest.mark.integration
    def test_update_nonexistent_policy(self, api_headers, sample_policy_payload):
        """Test updating policy that doesn't exist."""
        response = requests.put(
            f"{API_BASE_URL}/v1/policies/agent-config-nonexistent",
            json=sample_policy_payload,
            headers=api_headers
        )

        # Should return 404 Not Found
        assert response.status_code == 404
        data = response.json()
        assert data['success'] is False
        assert 'not found' in data['error'].lower()

    @pytest.mark.integration
    def test_delete_nonexistent_policy(self, api_headers):
        """Test deleting policy that doesn't exist."""
        response = requests.delete(
            f"{API_BASE_URL}/v1/policies/agent-config-nonexistent",
            headers=api_headers
        )

        # Should return 404 Not Found
        assert response.status_code == 404

    @pytest.mark.integration
    def test_get_nonexistent_policy(self):
        """Test getting policy that doesn't exist."""
        response = requests.get(
            f"{API_BASE_URL}/v1/policies/agent-config-nonexistent"
        )

        # Should return 404 Not Found
        assert response.status_code == 404


class TestPolicyAuditTrail:
    """Tests for audit trail verification."""

    @pytest.mark.integration
    def test_audit_trail_created(self, api_headers, sample_policy_payload, cleanup_policy):
        """Verify audit trail is created for policy operations."""
        # Create policy with specific operator
        custom_headers = api_headers.copy()
        custom_headers['X-Operator-Email'] = "audit-test@sentra.com"

        response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=custom_headers
        )

        assert response.status_code == 201
        policy_id = response.json()['policy_id']
        cleanup_policy.append(policy_id)

        time.sleep(1)

        # Fetch policy and verify operator context
        get_response = requests.get(
            f"{API_BASE_URL}/v1/policies/{policy_id}",
            params={"include_content": False}
        )

        assert get_response.status_code == 200
        metadata = get_response.json()['metadata']

        # Verify audit fields
        assert 'created_at' in metadata
        assert 'created_by' in metadata
        assert 'updated_at' in metadata


@pytest.mark.skipif(
    os.getenv("SKIP_INTEGRATION_TESTS") == "true",
    reason="Integration tests skipped (set SKIP_INTEGRATION_TESTS=false to run)"
)
class TestPerformance:
    """Performance tests for policy operations."""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_create_policy_performance(self, api_headers, sample_policy_payload):
        """Test policy creation performance."""
        import time

        start_time = time.time()

        response = requests.post(
            f"{API_BASE_URL}/v1/policies",
            json=sample_policy_payload,
            headers=api_headers,
            timeout=5  # 5 second timeout
        )

        elapsed_time = time.time() - start_time

        # Cleanup
        if response.status_code == 201:
            policy_id = response.json()['policy_id']
            requests.delete(f"{API_BASE_URL}/v1/policies/{policy_id}", headers=api_headers)

        # Assert performance
        assert elapsed_time < 2.0, f"Policy creation took {elapsed_time:.2f}s (should be < 2s)"
        assert response.status_code == 201
