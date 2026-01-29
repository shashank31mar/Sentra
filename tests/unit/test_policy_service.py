"""
Unit Tests for PolicyService CRUD Operations

Tests create_policy, update_policy, delete_policy, get_policy_by_id methods.
Reference: Workstream 11 - LLD 11 Section 5.2

Target: >80% coverage on policy_service.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime
import hashlib
import yaml


# Mock imports for testing
@pytest.fixture
def mock_policy_service():
    """Create PolicyService with mocked dependencies."""
    with patch('app.services.policy_service.boto3'), \
         patch('app.services.policy_service.PolicyValidator'), \
         patch('app.services.policy_service.S3PolicyStore'), \
         patch('app.services.policy_service.AuditLogger'):

        from app.services.policy_service import PolicyService
        service = PolicyService()

        # Mock dependencies
        service.metadata_table = Mock()
        service.validator = Mock()
        service.s3_store = Mock()
        service.audit_logger = Mock()
        service.audit_logger.log_mutation = AsyncMock()

        return service


@pytest.fixture
def sample_policy_data():
    """Sample policy data for testing."""
    return {
        "schema_version": "v1",
        "agent_id": "test-agent",
        "name": "Test Policy",
        "version": "1.0.0",
        "description": "Test policy description",
        "allowed_tools": ["tool_1", "tool_2"],
        "policies": [
            {
                "policy_id": "pol-001",
                "name": "Test Rule",
                "description": "Test rule description",
                "rule": "parameter <= 1000",
                "action": "DENY",
                "severity": "high",
                "enabled": True
            }
        ]
    }


class TestPolicyServiceCreate:
    """Tests for create_policy method."""

    @pytest.mark.asyncio
    async def test_create_policy_success(self, mock_policy_service, sample_policy_data):
        """Test successful policy creation."""
        # Setup mocks
        mock_policy_service.validator.validate_policy.return_value = (True, None)
        mock_policy_service.metadata_table.get_item.return_value = {}  # Policy doesn't exist
        mock_policy_service.s3_store.upload = AsyncMock(return_value="s3-version-123")

        # Execute
        result = await mock_policy_service.create_policy(
            policy_data=sample_policy_data,
            operator_email="test@example.com"
        )

        # Assert
        assert result['success'] is True
        assert result['policy_id'] == "agent-config-test-agent"
        assert result['version'] == "1.0.0"
        assert 's3_key' in result
        assert 's3_version_id' in result
        assert result['message'] == "Policy created successfully"

        # Verify DynamoDB put_item called
        mock_policy_service.metadata_table.put_item.assert_called_once()
        put_item_args = mock_policy_service.metadata_table.put_item.call_args[1]
        assert put_item_args['Item']['policy_id'] == "agent-config-test-agent"
        assert put_item_args['Item']['agent_id'] == "test-agent"
        assert put_item_args['Item']['status'] == "active"

        # Verify S3 upload called
        mock_policy_service.s3_store.upload.assert_called_once()

        # Verify audit log called
        mock_policy_service.audit_logger.log_mutation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_policy_validation_failure(self, mock_policy_service, sample_policy_data):
        """Test policy creation with validation failure."""
        # Setup validation failure
        mock_policy_service.validator.validate_policy.return_value = (
            False,
            ["Agent 'test-agent' not found", "Tool 'tool_1' not found"]
        )

        # Execute and expect exception
        from app.services.policy_service import ValidationException
        with pytest.raises(ValidationException) as exc_info:
            await mock_policy_service.create_policy(
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )

        # Verify no DynamoDB or S3 operations
        mock_policy_service.metadata_table.put_item.assert_not_called()
        mock_policy_service.s3_store.upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_policy_already_exists(self, mock_policy_service, sample_policy_data):
        """Test policy creation when policy already exists."""
        # Setup mocks
        mock_policy_service.validator.validate_policy.return_value = (True, None)
        mock_policy_service.metadata_table.get_item.return_value = {
            'Item': {'policy_id': 'agent-config-test-agent', 'version': '1.0.0'}
        }

        # Execute and expect exception
        from app.services.policy_service import ConflictException
        with pytest.raises(ConflictException) as exc_info:
            await mock_policy_service.create_policy(
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )

        assert "already exists" in str(exc_info.value)


class TestPolicyServiceUpdate:
    """Tests for update_policy method."""

    @pytest.mark.asyncio
    async def test_update_policy_success(self, mock_policy_service, sample_policy_data):
        """Test successful policy update."""
        # Setup mocks
        existing_policy = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'version': '1.0.0',
                'status': 'active'
            }
        }
        mock_policy_service.metadata_table.get_item.return_value = existing_policy
        mock_policy_service.validator.validate_policy.return_value = (True, None)
        mock_policy_service.s3_store.upload = AsyncMock(return_value="s3-version-456")

        # Update version
        sample_policy_data['version'] = '1.1.0'

        # Execute
        result = await mock_policy_service.update_policy(
            policy_id="agent-config-test-agent",
            policy_data=sample_policy_data,
            operator_email="test@example.com"
        )

        # Assert
        assert result['success'] is True
        assert result['policy_id'] == "agent-config-test-agent"
        assert result['version'] == "1.1.0"
        assert result['previous_version'] == "1.0.0"
        assert result['message'] == "Policy updated successfully"

        # Verify DynamoDB update called
        mock_policy_service.metadata_table.update_item.assert_called_once()

        # Verify S3 upload called
        mock_policy_service.s3_store.upload.assert_called_once()

        # Verify audit log
        mock_policy_service.audit_logger.log_mutation.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_policy_not_found(self, mock_policy_service, sample_policy_data):
        """Test update when policy doesn't exist."""
        # Setup mock - policy not found
        mock_policy_service.metadata_table.get_item.return_value = {}

        # Execute and expect exception
        from app.services.policy_service import NotFoundException
        with pytest.raises(NotFoundException):
            await mock_policy_service.update_policy(
                policy_id="agent-config-nonexistent",
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )

    @pytest.mark.asyncio
    async def test_update_disabled_policy(self, mock_policy_service, sample_policy_data):
        """Test update of disabled policy (should fail)."""
        # Setup mock - policy is disabled
        existing_policy = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'version': '1.0.0',
                'status': 'disabled'
            }
        }
        mock_policy_service.metadata_table.get_item.return_value = existing_policy

        # Execute and expect exception
        from app.services.policy_service import ForbiddenException
        with pytest.raises(ForbiddenException) as exc_info:
            await mock_policy_service.update_policy(
                policy_id="agent-config-test-agent",
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )

        assert "disabled" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_policy_auto_increment_version(self, mock_policy_service, sample_policy_data):
        """Test auto-increment version when not provided."""
        # Setup mocks
        existing_policy = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'version': '1.0.0',
                'status': 'active'
            }
        }
        mock_policy_service.metadata_table.get_item.return_value = existing_policy
        mock_policy_service.validator.validate_policy.return_value = (True, None)
        mock_policy_service.s3_store.upload = AsyncMock(return_value="s3-version-789")

        # Remove version to test auto-increment
        policy_data_no_version = sample_policy_data.copy()
        del policy_data_no_version['version']

        # Execute
        result = await mock_policy_service.update_policy(
            policy_id="agent-config-test-agent",
            policy_data=policy_data_no_version,
            operator_email="test@example.com"
        )

        # Assert version was auto-incremented
        assert result['version'] == "1.0.1"  # Auto-incremented from 1.0.0


class TestPolicyServiceDelete:
    """Tests for delete_policy method."""

    @pytest.mark.asyncio
    async def test_delete_policy_success(self, mock_policy_service):
        """Test successful soft delete."""
        # Setup mock
        existing_policy = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'created_by': 'user@example.com'
            }
        }
        mock_policy_service.metadata_table.get_item.return_value = existing_policy

        # Execute
        result = await mock_policy_service.delete_policy(
            policy_id="agent-config-test-agent",
            operator_email="test@example.com"
        )

        # Assert
        assert result['success'] is True
        assert result['status'] == 'disabled'
        assert result['message'] == "Policy disabled successfully"

        # Verify DynamoDB update called (soft delete)
        mock_policy_service.metadata_table.update_item.assert_called_once()
        update_args = mock_policy_service.metadata_table.update_item.call_args[1]
        assert ':disabled' in update_args['ExpressionAttributeValues']
        assert update_args['ExpressionAttributeValues'][':disabled'] == 'disabled'

        # Verify audit log
        mock_policy_service.audit_logger.log_mutation.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_policy_not_found(self, mock_policy_service):
        """Test delete when policy doesn't exist."""
        # Setup mock - policy not found
        mock_policy_service.metadata_table.get_item.return_value = {}

        # Execute and expect exception
        from app.services.policy_service import NotFoundException
        with pytest.raises(NotFoundException):
            await mock_policy_service.delete_policy(
                policy_id="agent-config-nonexistent",
                operator_email="test@example.com"
            )

    @pytest.mark.asyncio
    async def test_delete_system_policy(self, mock_policy_service):
        """Test delete of system policy (should fail)."""
        # Setup mock - system policy
        existing_policy = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'created_by': 'system'
            }
        }
        mock_policy_service.metadata_table.get_item.return_value = existing_policy

        # Execute and expect exception
        from app.services.policy_service import ForbiddenException
        with pytest.raises(ForbiddenException) as exc_info:
            await mock_policy_service.delete_policy(
                policy_id="agent-config-test-agent",
                operator_email="test@example.com"
            )

        assert "system" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_policy_idempotent(self, mock_policy_service):
        """Test that deleting already disabled policy is idempotent."""
        # Setup mock - already disabled
        existing_policy = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'created_by': 'user@example.com',
                'status': 'disabled'
            }
        }
        mock_policy_service.metadata_table.get_item.return_value = existing_policy

        # Execute (should succeed even though already disabled)
        result = await mock_policy_service.delete_policy(
            policy_id="agent-config-test-agent",
            operator_email="test@example.com"
        )

        # Assert success (idempotent)
        assert result['success'] is True
        assert result['status'] == 'disabled'


class TestPolicyServiceGet:
    """Tests for get_policy_by_id method."""

    @pytest.mark.asyncio
    async def test_get_policy_with_content(self, mock_policy_service):
        """Test get policy with S3 content."""
        # Setup mocks
        metadata = {
            'policy_id': 'agent-config-test-agent',
            'agent_id': 'test-agent',
            'version': '1.0.0',
            's3_key': 'policies/agents/test-agent/v1.0.0.yaml',
            's3_version_id': 'version-123'
        }
        mock_policy_service.metadata_table.get_item.return_value = {'Item': metadata}

        s3_content = """
schema_version: v1
policy_id: agent-config-test-agent
agent_id: test-agent
version: 1.0.0
allowed_tools:
  - tool_1
policies:
  - policy_id: pol-001
    name: Test Rule
    rule: parameter <= 1000
    action: DENY
    severity: high
"""
        mock_policy_service.s3_store.download = AsyncMock(return_value=s3_content)

        # Execute
        result = await mock_policy_service.get_policy_by_id(
            policy_id="agent-config-test-agent",
            include_content=True
        )

        # Assert
        assert result['success'] is True
        assert result['policy_id'] == "agent-config-test-agent"
        assert result['metadata'] == metadata
        assert result['content'] is not None
        assert result['content']['agent_id'] == 'test-agent'

        # Verify S3 download was called
        mock_policy_service.s3_store.download.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_policy_without_content(self, mock_policy_service):
        """Test get policy without S3 content."""
        # Setup mock
        metadata = {
            'policy_id': 'agent-config-test-agent',
            'agent_id': 'test-agent',
            'version': '1.0.0'
        }
        mock_policy_service.metadata_table.get_item.return_value = {'Item': metadata}

        # Execute
        result = await mock_policy_service.get_policy_by_id(
            policy_id="agent-config-test-agent",
            include_content=False
        )

        # Assert
        assert result['success'] is True
        assert result['content'] is None

        # Verify S3 download was NOT called
        mock_policy_service.s3_store.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_policy_not_found(self, mock_policy_service):
        """Test get policy that doesn't exist."""
        # Setup mock - policy not found
        mock_policy_service.metadata_table.get_item.return_value = {}

        # Execute and expect exception
        from app.services.policy_service import NotFoundException
        with pytest.raises(NotFoundException):
            await mock_policy_service.get_policy_by_id(
                policy_id="agent-config-nonexistent",
                include_content=True
            )


class TestPolicyServiceHelpers:
    """Tests for helper methods."""

    def test_calculate_severity_breakdown(self, mock_policy_service):
        """Test severity breakdown calculation."""
        policies = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]

        result = mock_policy_service._calculate_severity_breakdown(policies)

        assert result == {
            "critical": 1,
            "high": 2,
            "medium": 1,
            "low": 1
        }

    def test_increment_version(self, mock_policy_service):
        """Test version auto-increment."""
        assert mock_policy_service._increment_version("1.0.0") == "1.0.1"
        assert mock_policy_service._increment_version("1.0.9") == "1.0.10"
        assert mock_policy_service._increment_version("2.5.99") == "2.5.100"
