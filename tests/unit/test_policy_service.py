"""
Unit Tests for PolicyService CRUD Operations

Tests create_policy, update_policy, delete_policy, get_policy methods.
Reference: Workstream 11 - LLD 11 Section 5.2 (updated for the post-CT11 /
workstream-T7 architecture — see the fixture docstring).

Target: exercise the real CRUD contract (create success / validation-failure /
already-exists; update success / not-found / disabled / auto-increment; delete
success / not-found / system-policy / idempotent; get found & not-found;
severity breakdown; version increment).
"""

import pytest
from unittest.mock import Mock, patch, PropertyMock, AsyncMock


@pytest.fixture
def mock_policy_service():
    """Create PolicyService with mocked dependencies.

    ARCHITECTURE DRIFT this fixture accounts for (why it no longer looks like
    the old one that set service.validator / service.s3_store /
    service.audit_logger / service.metadata_table):

    * PolicyService.__init__ only builds region + boto3 resource/clients + cache.
      It does NOT hold validator / s3_store / audit_logger / metadata_table
      attributes anymore.
    * The write-path deps are LAZY-IMPORTED INSIDE the methods:
        create_policy / update_policy do
            from app.services.policy_validator import PolicyValidator
            from app.utils.s3_policy_store   import S3PolicyStore
            from app.utils.metrics_publisher import MetricsPublisher
      so they must be patched WHERE THEY LIVE (their real modules), not on the
      policy_service module namespace.
    * The metadata table is a @property `policies_metadata_table` resolved
      per-call via tenancy.table_name('policies_metadata'). We patch that
      property to return a single mock table (`mock_table`) so get_item /
      put_item / update_item are all observable on one object.
    * There is no AuditLogger: mutations are logged via `_log_audit`
      (plain logger.info). So there is nothing to assert on an audit-logger
      mock; instead create/update/delete are verified by their DDB writes.

    Cedar is left at its default (disabled under system python3, no CEDAR_ENABLED
    env), so `_maybe_write_cedar` is a no-op returning (FORMAT_YAML, None) and no
    cedarpy import is needed. `settings.s3_bucket` is used for the S3 key/bucket.
    """
    with patch('app.services.policy_service.boto3'), \
         patch('app.services.policy_service.get_cache_manager') as mock_get_cache:

        # Cache: get() returns None so reads always fall through to DDB; set()
        # and clear() are no-ops we can observe.
        cache = Mock()
        cache.get = Mock(return_value=None)
        cache.set = Mock()
        cache.clear = Mock()
        mock_get_cache.return_value = cache

        from app.services.policy_service import PolicyService
        service = PolicyService()

        # Single mock DynamoDB metadata table behind the read-only property.
        mock_table = Mock()
        table_patcher = patch.object(
            PolicyService, 'policies_metadata_table',
            new_callable=PropertyMock, return_value=mock_table,
        )
        table_patcher.start()

        # Expose the mock table + cache for tests to drive/inspect.
        service._mock_table = mock_table   # test-only handle
        service._mock_cache = cache        # test-only handle

        try:
            yield service
        finally:
            table_patcher.stop()


@pytest.fixture
def sample_policy_data():
    """Sample policy data for testing (as a create request would arrive)."""
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


def _patch_write_deps(validate_return=(True, None), s3_version="s3-version-123"):
    """Context managers patching the lazy-imported write-path deps at their
    real module source. Returns (validator_cls, s3_store_cls, metrics_cls)
    patch objects so a test can start/inspect them.

    - PolicyValidator().validate_policy(...) -> validate_return
    - S3PolicyStore(bucket).upload(...) (async) -> s3_version
    - MetricsPublisher() with async publish_* methods (no-op)
    """
    validator_patch = patch('app.services.policy_validator.PolicyValidator')
    s3_patch = patch('app.utils.s3_policy_store.S3PolicyStore')
    metrics_patch = patch('app.utils.metrics_publisher.MetricsPublisher')

    validator_cls = validator_patch.start()
    s3_cls = s3_patch.start()
    metrics_cls = metrics_patch.start()

    validator_cls.return_value.validate_policy.return_value = validate_return

    s3_instance = s3_cls.return_value
    s3_instance.upload = AsyncMock(return_value=s3_version)

    metrics_instance = metrics_cls.return_value
    metrics_instance.publish_policy_validation_metric = AsyncMock()
    metrics_instance.publish_policy_crud_metric = AsyncMock()

    return (validator_patch, s3_patch, metrics_patch, validator_cls, s3_cls, metrics_cls)


class TestPolicyServiceCreate:
    """Tests for create_policy method."""

    @pytest.mark.asyncio
    async def test_create_policy_success(self, mock_policy_service, sample_policy_data):
        """Test successful policy creation."""
        # Policy doesn't exist yet (get_policy -> get_item returns no Item).
        mock_policy_service._mock_table.get_item.return_value = {}

        vp, sp, mp, validator_cls, s3_cls, metrics_cls = _patch_write_deps(
            s3_version="s3-version-123")
        try:
            result = await mock_policy_service.create_policy(
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )
        finally:
            vp.stop(); sp.stop(); mp.stop()

        # Assert result envelope
        assert result['success'] is True
        assert result['policy_id'] == "agent-config-test-agent"
        assert result['version'] == "1.0.0"
        assert 's3_key' in result
        assert result['s3_version_id'] == "s3-version-123"
        assert result['message'] == "Policy created successfully"

        # Verify DynamoDB put_item called with the computed metadata item.
        mock_policy_service._mock_table.put_item.assert_called_once()
        put_item_args = mock_policy_service._mock_table.put_item.call_args[1]
        assert put_item_args['Item']['policy_id'] == "agent-config-test-agent"
        assert put_item_args['Item']['agent_id'] == "test-agent"
        assert put_item_args['Item']['status'] == "active"

        # Verify S3 upload happened once, and validation ran.
        s3_cls.return_value.upload.assert_called_once()
        validator_cls.return_value.validate_policy.assert_called_once()

        # Cache invalidated after a successful create.
        mock_policy_service._mock_cache.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_policy_validation_failure(self, mock_policy_service, sample_policy_data):
        """Test policy creation with validation failure raises ValidationException."""
        vp, sp, mp, validator_cls, s3_cls, metrics_cls = _patch_write_deps(
            validate_return=(False, ["Agent 'test-agent' not found", "bad thing"]))
        try:
            from app.services.policy_service import ValidationException
            with pytest.raises(ValidationException):
                await mock_policy_service.create_policy(
                    policy_data=sample_policy_data,
                    operator_email="test@example.com"
                )
        finally:
            vp.stop(); sp.stop(); mp.stop()

        # No DynamoDB or S3 write when validation fails.
        mock_policy_service._mock_table.put_item.assert_not_called()
        s3_cls.return_value.upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_policy_already_exists(self, mock_policy_service, sample_policy_data):
        """Test policy creation when policy already exists raises ConflictException."""
        # get_policy -> get_item returns an existing Item.
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {'policy_id': 'agent-config-test-agent', 'version': '1.0.0'}
        }

        vp, sp, mp, validator_cls, s3_cls, metrics_cls = _patch_write_deps()
        try:
            from app.services.policy_service import ConflictException
            with pytest.raises(ConflictException) as exc_info:
                await mock_policy_service.create_policy(
                    policy_data=sample_policy_data,
                    operator_email="test@example.com"
                )
        finally:
            vp.stop(); sp.stop(); mp.stop()

        assert "already exists" in str(exc_info.value)
        # No write on conflict.
        mock_policy_service._mock_table.put_item.assert_not_called()


class TestPolicyServiceUpdate:
    """Tests for update_policy method."""

    @pytest.mark.asyncio
    async def test_update_policy_success(self, mock_policy_service, sample_policy_data):
        """Test successful policy update."""
        # get_policy -> existing active policy.
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'version': '1.0.0',
                'status': 'active'
            }
        }

        sample_policy_data['version'] = '1.1.0'

        vp, sp, mp, validator_cls, s3_cls, metrics_cls = _patch_write_deps(
            s3_version="s3-version-456")
        try:
            result = await mock_policy_service.update_policy(
                policy_id="agent-config-test-agent",
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )
        finally:
            vp.stop(); sp.stop(); mp.stop()

        assert result['success'] is True
        assert result['policy_id'] == "agent-config-test-agent"
        assert result['version'] == "1.1.0"
        assert result['previous_version'] == "1.0.0"
        assert result['message'] == "Policy updated successfully"

        # Verify DynamoDB update + S3 upload.
        mock_policy_service._mock_table.update_item.assert_called_once()
        s3_cls.return_value.upload.assert_called_once()
        mock_policy_service._mock_cache.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_policy_not_found(self, mock_policy_service, sample_policy_data):
        """Test update when policy doesn't exist raises NotFoundException."""
        mock_policy_service._mock_table.get_item.return_value = {}

        from app.services.policy_service import NotFoundException
        with pytest.raises(NotFoundException):
            await mock_policy_service.update_policy(
                policy_id="agent-config-nonexistent",
                policy_data=sample_policy_data,
                operator_email="test@example.com"
            )

    @pytest.mark.asyncio
    async def test_update_disabled_policy(self, mock_policy_service, sample_policy_data):
        """Test update of a disabled policy is forbidden."""
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'version': '1.0.0',
                'status': 'disabled'
            }
        }

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
        """Test auto-increment version when the edit omits version."""
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'version': '1.0.0',
                'status': 'active'
            }
        }

        policy_data_no_version = sample_policy_data.copy()
        del policy_data_no_version['version']

        vp, sp, mp, validator_cls, s3_cls, metrics_cls = _patch_write_deps(
            s3_version="s3-version-789")
        try:
            result = await mock_policy_service.update_policy(
                policy_id="agent-config-test-agent",
                policy_data=policy_data_no_version,
                operator_email="test@example.com"
            )
        finally:
            vp.stop(); sp.stop(); mp.stop()

        # Auto-incremented patch version 1.0.0 -> 1.0.1.
        assert result['version'] == "1.0.1"


class TestPolicyServiceDelete:
    """Tests for delete_policy method (soft delete → status=disabled)."""

    @pytest.mark.asyncio
    async def test_delete_policy_success(self, mock_policy_service):
        """Test successful soft delete."""
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'created_by': 'user@example.com'
            }
        }

        result = await mock_policy_service.delete_policy(
            policy_id="agent-config-test-agent",
            operator_email="test@example.com"
        )

        assert result['success'] is True
        assert result['status'] == 'disabled'
        assert result['message'] == "Policy disabled successfully"

        # Soft-delete writes status=disabled via update_item.
        mock_policy_service._mock_table.update_item.assert_called_once()
        update_args = mock_policy_service._mock_table.update_item.call_args[1]
        assert update_args['ExpressionAttributeValues'][':disabled'] == 'disabled'
        mock_policy_service._mock_cache.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_policy_not_found(self, mock_policy_service):
        """Test delete when policy doesn't exist raises NotFoundException."""
        mock_policy_service._mock_table.get_item.return_value = {}

        from app.services.policy_service import NotFoundException
        with pytest.raises(NotFoundException):
            await mock_policy_service.delete_policy(
                policy_id="agent-config-nonexistent",
                operator_email="test@example.com"
            )

    @pytest.mark.asyncio
    async def test_delete_system_policy(self, mock_policy_service):
        """Test delete of a system policy is forbidden."""
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'created_by': 'system'
            }
        }

        from app.services.policy_service import ForbiddenException
        with pytest.raises(ForbiddenException) as exc_info:
            await mock_policy_service.delete_policy(
                policy_id="agent-config-test-agent",
                operator_email="test@example.com"
            )

        assert "system" in str(exc_info.value).lower()
        # Guarded: no write when forbidden.
        mock_policy_service._mock_table.update_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_policy_idempotent(self, mock_policy_service):
        """Test that deleting an already-disabled policy is idempotent."""
        mock_policy_service._mock_table.get_item.return_value = {
            'Item': {
                'policy_id': 'agent-config-test-agent',
                'created_by': 'user@example.com',
                'status': 'disabled'
            }
        }

        result = await mock_policy_service.delete_policy(
            policy_id="agent-config-test-agent",
            operator_email="test@example.com"
        )

        assert result['success'] is True
        assert result['status'] == 'disabled'


class TestPolicyServiceGet:
    """Tests for get_policy (metadata) — the current read contract.

    CONTRACT CHANGE: the old tests called `get_policy_by_id(policy_id,
    include_content=...)` and asserted a `{'success': True, 'metadata':...,
    'content':...}` envelope plus an `s3_store.download` call. That method no
    longer exists. The current API is:
      * get_policy(policy_id)         -> metadata dict, or None if not found
      * get_policy_content(policy_id) -> full dict w/ content (S3 via
                                         s3_policy_store.get_policy_object)
    get_policy returns the raw metadata dict (enriched with match_count_24h),
    NOT a success-envelope, and returns None (does not raise) when absent. We
    updated these tests to the real get_policy contract. The S3 content path
    (get_policy_content) is already covered by the controller's own suite
    (src/security-controller/tests/unit/test_policy_service.py
    ::TestPolicyServiceGetPolicyContent), so we do not duplicate it here.
    """

    @pytest.mark.asyncio
    async def test_get_policy_found(self, mock_policy_service):
        """get_policy returns the metadata dict (enriched) when found."""
        metadata = {
            'policy_id': 'agent-config-test-agent',
            'agent_id': 'test-agent',
            'version': '1.0.0',
        }
        mock_policy_service._mock_table.get_item.return_value = {'Item': dict(metadata)}

        result = await mock_policy_service.get_policy("agent-config-test-agent")

        assert result is not None
        assert result['policy_id'] == "agent-config-test-agent"
        assert result['agent_id'] == "test-agent"
        # Enriched with a match count (MVP: 0).
        assert result['match_count_24h'] == 0
        mock_policy_service._mock_table.get_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_policy_not_found(self, mock_policy_service):
        """get_policy returns None (does not raise) when the policy is absent."""
        mock_policy_service._mock_table.get_item.return_value = {}

        result = await mock_policy_service.get_policy("agent-config-nonexistent")

        assert result is None


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
        """Test version auto-increment (patch bump)."""
        assert mock_policy_service._increment_version("1.0.0") == "1.0.1"
        assert mock_policy_service._increment_version("1.0.9") == "1.0.10"
        assert mock_policy_service._increment_version("2.5.99") == "2.5.100"
