"""
Unit Tests for SigmaRulesService

Tests Sigma rules queries with mocked dependencies.
Target: >90% code coverage
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from decimal import Decimal

from app.services.sigma_rules_service import SigmaRulesService, SigmaRulesServiceError


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
    with patch('app.services.sigma_rules_service.get_cache_manager') as mock:
        cache = Mock()
        cache.get = Mock(return_value=None)
        cache.set = Mock()
        cache.invalidate = Mock()
        mock.return_value = cache
        yield cache


@pytest.fixture
def sample_sigma_rule():
    """Sample Sigma rule metadata from DynamoDB"""
    return {
        'rule_id': 'sigma-llm-001',
        'title': 'Test Sigma Rule',
        'description': 'Test rule description',
        'status': 'stable',
        'level': 'high',
        'patterns_count': '10',
        'tags': ['attack.llm01', 'owasp.llm.top10.2025'],
        'stats': {
            'match_count_24h': Decimal('5'),
            'match_count_7d': Decimal('20'),
            'last_matched': '2025-01-21T10:00:00Z'
        },
        's3_bucket': 'test-bucket',
        's3_key': 'sigma_rules/llm/test-rule.yaml',
        'created_at': '2025-01-21T10:00:00Z'
    }


class TestSigmaRulesServiceListRules:
    """Tests for list_sigma_rules() method"""
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_no_filters(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test listing all Sigma rules without filters"""
        # Setup mocks
        mock_table = Mock()
        mock_table.scan.return_value = {
            'Items': [sample_sigma_rule]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules()
        
        # Assertions
        assert result['total'] == 1
        assert len(result['rules']) == 1
        assert result['rules'][0]['rule_id'] == 'sigma-llm-001'
        assert result['next_token'] is None
        
        # Verify scan was called
        mock_table.scan.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_by_status(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test listing Sigma rules by status"""
        # Setup mocks
        mock_table = Mock()
        mock_table.query.return_value = {
            'Items': [sample_sigma_rule]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules(status='stable')
        
        # Assertions
        assert result['total'] == 1
        assert result['rules'][0]['status'] == 'stable'
        
        # Verify query was called with status-index
        mock_table.query.assert_called_once()
        call_args = mock_table.query.call_args
        assert call_args[1]['IndexName'] == 'status-index'
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_by_level(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test listing Sigma rules by level"""
        # Setup mocks
        mock_table = Mock()
        mock_table.query.return_value = {
            'Items': [sample_sigma_rule]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules(level='high')
        
        # Assertions
        assert result['total'] == 1
        assert result['rules'][0]['level'] == 'high'
        
        # Verify query was called with level-index
        mock_table.query.assert_called_once()
        call_args = mock_table.query.call_args
        assert call_args[1]['IndexName'] == 'level-index'
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_with_both_filters(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test listing Sigma rules with both status and level"""
        # Setup mocks
        rule2 = sample_sigma_rule.copy()
        rule2['level'] = 'medium'
        
        mock_table = Mock()
        mock_table.query.return_value = {
            'Items': [sample_sigma_rule, rule2]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules(status='stable', level='high')
        
        # Assertions - should filter out medium level rule
        assert result['total'] == 1
        assert result['rules'][0]['level'] == 'high'
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_sorted_by_match_count(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test that rules are sorted by match_count_24h descending"""
        # Setup mocks with multiple rules
        rule1 = {**sample_sigma_rule, 'rule_id': 'rule-1', 'stats': {'match_count_24h': Decimal('10')}}
        rule2 = {**sample_sigma_rule, 'rule_id': 'rule-2', 'stats': {'match_count_24h': Decimal('50')}}
        rule3 = {**sample_sigma_rule, 'rule_id': 'rule-3', 'stats': {'match_count_24h': Decimal('5')}}
        
        mock_table = Mock()
        mock_table.scan.return_value = {
            'Items': [rule1, rule2, rule3]
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules()
        
        # Assertions - should be sorted by match count descending
        assert result['rules'][0]['rule_id'] == 'rule-2'  # 50 matches
        assert result['rules'][1]['rule_id'] == 'rule-1'  # 10 matches
        assert result['rules'][2]['rule_id'] == 'rule-3'  # 5 matches
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_with_limit(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test listing Sigma rules with limit"""
        # Setup mocks with multiple rules
        rules = [
            {**sample_sigma_rule, 'rule_id': f'rule-{i}', 'stats': {'match_count_24h': Decimal(str(i))}}
            for i in range(10)
        ]
        
        mock_table = Mock()
        # DDB returns a LastEvaluatedKey when more results exist — drives next_token.
        mock_table.scan.return_value = {
            'Items': rules,
            'LastEvaluatedKey': {'rule_id': 'rule-4'},
        }
        mock_dynamodb.return_value.Table.return_value = mock_table

        # Create service and test with limit=5
        service = SigmaRulesService()
        result = await service.list_sigma_rules(limit=5)

        # Assertions
        assert len(result['rules']) == 5
        assert result['total'] == 10
        assert result['next_token'] is not None  # more pages available
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_limit_capped_at_200(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test that limit is capped at 200"""
        # Setup mocks
        mock_table = Mock()
        mock_table.scan.return_value = {'Items': [sample_sigma_rule]}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test with limit > 200
        service = SigmaRulesService()
        result = await service.list_sigma_rules(limit=500)
        
        # Verify limit was capped
        call_args = mock_table.scan.call_args
        assert call_args[1]['Limit'] == 200
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_cache_hit(self, mock_dynamodb, mock_cache_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_data = {
            'rules': [{'rule_id': 'cached-rule'}],
            'total': 1,
            'next_token': None
        }
        mock_cache_manager.get.return_value = cached_data
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules()
        
        # Assertions
        assert result == cached_data
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.scan.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_list_sigma_rules_error_handling(self, mock_dynamodb, mock_cache_manager):
        """Test error handling returns empty array"""
        # Setup mock to raise exception
        mock_table = Mock()
        mock_table.scan.side_effect = Exception("DynamoDB error")
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.list_sigma_rules()
        
        # Assertions - should return empty array, not raise
        assert result['rules'] == []
        assert result['total'] == 0
        assert result['next_token'] is None
        assert 'error' in result


class TestSigmaRulesServiceGetRule:
    """Tests for get_sigma_rule() method"""
    
    @pytest.mark.asyncio
    async def test_get_sigma_rule_success(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test successful Sigma rule retrieval"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': sample_sigma_rule}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.get_sigma_rule('sigma-llm-001')
        
        # Assertions
        assert result is not None
        assert result['rule_id'] == 'sigma-llm-001'
    
    @pytest.mark.asyncio
    async def test_get_sigma_rule_not_found(self, mock_dynamodb, mock_cache_manager):
        """Test Sigma rule not found returns None"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {}  # No 'Item' key
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.get_sigma_rule('nonexistent-rule')
        
        # Assertions
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_sigma_rule_cache_hit(self, mock_dynamodb, mock_cache_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_rule = {'rule_id': 'cached-rule', 'title': 'Cached Rule'}
        mock_cache_manager.get.return_value = cached_rule
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.get_sigma_rule('cached-rule')
        
        # Assertions
        assert result == cached_rule
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.get_item.assert_not_called()


class TestSigmaRulesServiceGetRuleContent:
    """Tests for get_sigma_rule_content() method"""
    
    @pytest.mark.asyncio
    async def test_get_sigma_rule_content_success(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test successful Sigma rule content retrieval from S3"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': sample_sigma_rule}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock S3 client. The S3 get_object response is dict-like (Body is
        # accessed via `obj['Body']`), so we need MagicMock (which supports
        # __getitem__) rather than a plain Mock for the response object.
        with patch('app.services.sigma_rules_service.boto3.client') as mock_s3:
            s3_mock = Mock()
            body_mock = Mock()
            body_mock.read.return_value = b'title: Test Sigma Rule\ndetection:\n  condition: test'
            s3_obj = {'Body': body_mock}
            s3_mock.get_object.return_value = s3_obj
            mock_s3.return_value = s3_mock

            # Create service and test
            service = SigmaRulesService()
            result = await service.get_sigma_rule_content('sigma-llm-001')
        
        # Assertions
        assert result is not None
        assert 'metadata' in result
        assert result['metadata']['rule_id'] == 'sigma-llm-001'
    
    @pytest.mark.asyncio
    async def test_get_sigma_rule_content_no_s3_reference(self, mock_dynamodb, mock_cache_manager, sample_sigma_rule):
        """Test Sigma rule content when S3 reference is missing"""
        # Setup mocks - rule without S3 reference
        rule_no_s3 = sample_sigma_rule.copy()
        del rule_no_s3['s3_bucket']
        del rule_no_s3['s3_key']
        
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': rule_no_s3}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.get_sigma_rule_content('sigma-llm-001')
        
        # Assertions - should return metadata only
        assert result is not None
        assert result['rule_id'] == 'sigma-llm-001'
        assert 'metadata' not in result


class TestSigmaRulesServiceUpdateMatchCount:
    """Tests for update_rule_match_count() method"""
    
    @pytest.mark.asyncio
    async def test_update_rule_match_count_success(self, mock_dynamodb, mock_cache_manager):
        """Test successful match count update"""
        # Setup mocks
        mock_table = Mock()
        mock_table.update_item.return_value = {}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.update_rule_match_count('sigma-llm-001')
        
        # Assertions
        assert result == True
        
        # Verify update_item was called
        mock_table.update_item.assert_called_once()
        
        # Verify cache was invalidated
        mock_cache_manager.invalidate.assert_called_once_with('sigma_rule:sigma-llm-001')
    
    @pytest.mark.asyncio
    async def test_update_rule_match_count_with_custom_increment(self, mock_dynamodb, mock_cache_manager):
        """Test match count update with custom increment"""
        # Setup mocks
        mock_table = Mock()
        mock_table.update_item.return_value = {}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.update_rule_match_count('sigma-llm-001', increment=5)
        
        # Assertions
        assert result == True
        
        # Verify update_item was called with correct increment
        call_args = mock_table.update_item.call_args
        assert ':inc' in call_args[1]['ExpressionAttributeValues']
        assert call_args[1]['ExpressionAttributeValues'][':inc'] == 5
    
    @pytest.mark.asyncio
    async def test_update_rule_match_count_error_handling(self, mock_dynamodb, mock_cache_manager):
        """Test error handling returns False"""
        # Setup mock to raise exception
        mock_table = Mock()
        mock_table.update_item.side_effect = Exception("DynamoDB error")
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = SigmaRulesService()
        result = await service.update_rule_match_count('sigma-llm-001')
        
        # Assertions - should return False, not raise
        assert result == False
