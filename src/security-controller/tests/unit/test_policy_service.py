"""
Unit Tests for PolicyService

Tests policy queries with mocked dependencies.
Target: >90% code coverage
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch

from app.services.policy_service import PolicyService, PolicyServiceError


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource"""
    with patch('boto3.resource') as mock:
        yield mock


@pytest.fixture
def mock_s3_client():
    """Mock S3 client"""
    with patch('boto3.client') as mock:
        yield mock


@pytest.fixture
def mock_cache_manager():
    """Mock cache manager"""
    with patch('app.services.policy_service.get_cache_manager') as mock:
        cache = Mock()
        cache.get = Mock(return_value=None)
        cache.set = Mock()
        mock.return_value = cache
        yield cache


@pytest.fixture
def sample_policy():
    """Sample policy metadata from DynamoDB"""
    return {
        'policy_id': 'test-policy-001',
        'agent_id': 'test-agent',
        'name': 'Test Policy',
        'description': 'Test policy description',
        'status': 'active',
        'version': '1.0.0',
        's3_bucket': 'test-bucket',
        's3_key': 'policies/test-policy.yaml',
        'created_at': '2025-01-21T10:00:00Z'
    }


class TestPolicyServiceQueryPolicies:
    """Tests for query_policies() method"""
    
    @pytest.mark.asyncio
    async def test_query_policies_no_filters(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test querying all policies without filters"""
        # Setup mocks
        mock_table = Mock()
        mock_table.scan.return_value = {
            'Items': [sample_policy]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.query_policies()
        
        # Assertions
        assert result['total'] == 1
        assert len(result['policies']) == 1
        assert result['policies'][0]['policy_id'] == 'test-policy-001'
        assert result['policies'][0]['match_count_24h'] == 0
        assert result['next_token'] is None
        
        # Verify scan was called
        mock_table.scan.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_query_policies_by_agent_id(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test querying policies by agent_id"""
        # Setup mocks
        mock_table = Mock()
        mock_table.query.return_value = {
            'Items': [sample_policy]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.query_policies(agent_id='test-agent')
        
        # Assertions
        assert result['total'] == 1
        assert result['policies'][0]['agent_id'] == 'test-agent'
        
        # Verify query was called with agent-index
        mock_table.query.assert_called_once()
        call_args = mock_table.query.call_args
        assert call_args[1]['IndexName'] == 'agent-index'
    
    @pytest.mark.asyncio
    async def test_query_policies_by_status(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test querying policies by status"""
        # Setup mocks
        mock_table = Mock()
        mock_table.query.return_value = {
            'Items': [sample_policy]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.query_policies(status='active')
        
        # Assertions
        assert result['total'] == 1
        assert result['policies'][0]['status'] == 'active'
        
        # Verify query was called with status-index
        mock_table.query.assert_called_once()
        call_args = mock_table.query.call_args
        assert call_args[1]['IndexName'] == 'status-index'
    
    @pytest.mark.asyncio
    async def test_query_policies_with_both_filters(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test querying policies with both agent_id and status"""
        # Setup mocks
        policy2 = sample_policy.copy()
        policy2['status'] = 'inactive'
        
        mock_table = Mock()
        mock_table.query.return_value = {
            'Items': [sample_policy, policy2]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.query_policies(agent_id='test-agent', status='active')
        
        # Assertions - should filter out inactive policy
        assert result['total'] == 1
        assert result['policies'][0]['status'] == 'active'
    
    @pytest.mark.asyncio
    async def test_query_policies_with_limit(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test querying policies with limit"""
        # Setup mocks with multiple policies
        policies = [
            {**sample_policy, 'policy_id': f'policy-{i}'}
            for i in range(10)
        ]
        
        mock_table = Mock()
        # DDB returns a page plus a LastEvaluatedKey when more results exist —
        # that continuation key is what now drives next_token (canonical pagination).
        mock_table.scan.return_value = {
            'Items': policies,
            'LastEvaluatedKey': {'policy_id': 'policy-4'},
        }
        mock_dynamodb.return_value.Table.return_value = mock_table

        # Create service and test with limit=5
        service = PolicyService()
        result = await service.query_policies(limit=5)

        # Assertions
        assert len(result['policies']) == 5
        assert result['total'] == 10
        assert result['next_token'] is not None  # more pages available
    
    @pytest.mark.asyncio
    async def test_query_policies_limit_capped_at_200(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test that limit is capped at 200"""
        # Setup mocks
        mock_table = Mock()
        mock_table.scan.return_value = {'Items': [sample_policy]}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test with limit > 200
        service = PolicyService()
        result = await service.query_policies(limit=500)
        
        # Verify limit was capped
        call_args = mock_table.scan.call_args
        assert call_args[1]['Limit'] == 200
    
    @pytest.mark.asyncio
    async def test_query_policies_cursor_threads_exclusive_start_key(
        self, mock_dynamodb, mock_cache_manager, sample_policy
    ):
        """WS-21 T06: an opaque cursor decodes to a DDB ExclusiveStartKey."""
        from app.utils.pagination import encode_cursor

        mock_table = Mock()
        mock_table.scan.return_value = {'Items': [sample_policy]}
        mock_dynamodb.return_value.Table.return_value = mock_table

        cursor = encode_cursor({'policy_id': 'p-prev'})
        service = PolicyService()
        await service.query_policies(cursor=cursor)

        assert mock_table.scan.call_args.kwargs['ExclusiveStartKey'] == {'policy_id': 'p-prev'}

    @pytest.mark.asyncio
    async def test_query_policies_cache_hit(self, mock_dynamodb, mock_cache_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_data = {
            'policies': [{'policy_id': 'cached-policy'}],
            'total': 1,
            'next_token': None
        }
        mock_cache_manager.get.return_value = cached_data
        
        # Create service and test
        service = PolicyService()
        result = await service.query_policies()
        
        # Assertions
        assert result == cached_data
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.scan.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_query_policies_error_handling(self, mock_dynamodb, mock_cache_manager):
        """Test error handling returns empty array"""
        # Setup mock to raise exception
        mock_table = Mock()
        mock_table.scan.side_effect = Exception("DynamoDB error")
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.query_policies()
        
        # Assertions - should return empty array, not raise
        assert result['policies'] == []
        assert result['total'] == 0
        assert result['next_token'] is None
        assert 'error' in result


class TestPolicyServiceGetPolicy:
    """Tests for get_policy() method"""
    
    @pytest.mark.asyncio
    async def test_get_policy_success(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test successful policy retrieval"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': sample_policy}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.get_policy('test-policy-001')
        
        # Assertions
        assert result is not None
        assert result['policy_id'] == 'test-policy-001'
        assert result['match_count_24h'] == 0
    
    @pytest.mark.asyncio
    async def test_get_policy_not_found(self, mock_dynamodb, mock_cache_manager):
        """Test policy not found returns None"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {}  # No 'Item' key
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.get_policy('nonexistent-policy')
        
        # Assertions
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_policy_cache_hit(self, mock_dynamodb, mock_cache_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_policy = {'policy_id': 'cached-policy', 'name': 'Cached Policy'}
        mock_cache_manager.get.return_value = cached_policy
        
        # Create service and test
        service = PolicyService()
        result = await service.get_policy('cached-policy')
        
        # Assertions
        assert result == cached_policy
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.get_item.assert_not_called()


class TestPolicyServiceGetPolicyContent:
    """Tests for get_policy_content() method"""
    
    @pytest.mark.asyncio
    async def test_get_policy_content_success(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test successful policy content retrieval from S3"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': sample_policy}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock S3 client
        with patch('app.services.policy_service.boto3.client') as mock_s3:
            s3_mock = Mock()
            # Create a mock body object that can be subscripted
            mock_body = Mock()
            mock_body.read.return_value = b'policy_id: test-policy-001\nname: Test Policy'
            s3_obj = {'Body': mock_body}
            s3_mock.get_object.return_value = s3_obj
            mock_s3.return_value = s3_mock
            
            # Create service and test
            service = PolicyService()
            result = await service.get_policy_content('test-policy-001')
        
        # Assertions
        assert result is not None
        assert 'metadata' in result
        assert result['metadata']['policy_id'] == 'test-policy-001'
    
    @pytest.mark.asyncio
    async def test_get_policy_content_no_s3_reference(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test policy content when S3 reference is missing"""
        # Setup mocks - policy without S3 reference
        policy_no_s3 = sample_policy.copy()
        del policy_no_s3['s3_bucket']
        del policy_no_s3['s3_key']
        
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': policy_no_s3}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.get_policy_content('test-policy-001')
        
        # Assertions - should return metadata only
        assert result is not None
        assert result['policy_id'] == 'test-policy-001'
        assert 'metadata' not in result
    
    @pytest.mark.asyncio
    async def test_get_policy_content_not_found(self, mock_dynamodb, mock_cache_manager):
        """Test policy content when policy doesn't exist"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = PolicyService()
        result = await service.get_policy_content('nonexistent-policy')
        
        # Assertions
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_policy_content_s3_error(self, mock_dynamodb, mock_cache_manager, sample_policy):
        """Test error handling when S3 fails"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': sample_policy}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock S3 client to raise exception
        with patch('app.services.policy_service.boto3.client') as mock_s3:
            s3_mock = Mock()
            s3_mock.get_object.side_effect = Exception("S3 error")
            mock_s3.return_value = s3_mock
            
            # Create service and test
            service = PolicyService()
            result = await service.get_policy_content('test-policy-001')
        
        # Assertions - should return None on error
        assert result is None
