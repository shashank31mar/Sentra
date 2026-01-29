"""
Unit Tests for AgentService

Tests agent metadata aggregation with mocked dependencies.
Target: >90% code coverage
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal
from io import BytesIO

from app.services.agent_service import AgentService, AgentServiceError


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource"""
    with patch('boto3.resource') as mock:
        yield mock


@pytest.fixture
def mock_ecs_client():
    """Mock ECS client"""
    with patch('boto3.client') as mock:
        yield mock


@pytest.fixture
def mock_s3_client():
    """Mock S3 client"""
    with patch('app.services.agent_service.boto3.client') as mock:
        s3_mock = Mock()
        mock.return_value = s3_mock
        yield s3_mock


@pytest.fixture
def mock_cache_manager():
    """Mock cache manager"""
    with patch('app.services.agent_service.get_cache_manager') as mock:
        cache = Mock()
        cache.get = Mock(return_value=None)
        cache.set = Mock()
        mock.return_value = cache
        yield cache


@pytest.fixture
def mock_session_manager():
    """Mock session manager"""
    with patch('app.services.agent_service.SessionManager') as mock:
        session_mgr = Mock()
        session_mgr.get_active_sessions_count = AsyncMock(return_value=3)
        session_mgr.get_avg_trust_score = AsyncMock(return_value=95.0)
        session_mgr.query_sessions = AsyncMock(return_value={
            'sessions': [
                {'request_count': 100, 'trust_score': 90},
                {'request_count': 50, 'trust_score': 95}
            ]
        })
        mock.return_value = session_mgr
        yield session_mgr


@pytest.fixture
def sample_agent():
    """Sample agent data from DynamoDB"""
    return {
        'agent_id': 'test-agent',
        'name': 'Test Agent',
        'description': 'Test agent description',
        'status': 'active',
        'version': '1.0.0',
        'ecs_config': {
            'service_name': 'test-service',
            'container_port': '8080'
        },
        'created_at': '2025-01-21T10:00:00Z'
    }


@pytest.fixture
def sample_tool():
    """Sample tool data from DynamoDB"""
    return {
        'tool_id': 'test-tool',
        'name': 'Test Tool',
        'type': 'READ',
        'description': 'Test tool description',
        'rate_limit': {'requests_per_minute': Decimal('60')}
    }


class TestAgentServiceListAgents:
    """Tests for list_agents() method"""
    
    @pytest.mark.asyncio
    async def test_list_agents_success(self, mock_dynamodb, mock_cache_manager, mock_session_manager, sample_agent):
        """Test successful agent listing"""
        # Setup mocks
        mock_table = Mock()
        mock_table.scan.return_value = {
            'Items': [sample_agent],
            'LastEvaluatedKey': None
        }
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock ECS client
        with patch('app.services.agent_service.boto3.client') as mock_client:
            ecs_mock = Mock()
            ecs_mock.describe_services.return_value = {
                'services': [{
                    'desiredCount': 1,
                    'runningCount': 1,
                    'createdAt': Mock(tzinfo=Mock())
                }]
            }
            mock_client.return_value = ecs_mock
            
            # Create service and test
            service = AgentService()
            result = await service.list_agents()
        
        # Assertions
        assert result['total'] == 1
        assert len(result['agents']) == 1
        assert result['agents'][0]['agent_id'] == 'test-agent'
        assert result['agents'][0]['active_sessions'] == 3
        assert result['agents'][0]['trust_score_avg'] == 95.0
        
        # Verify cache was set
        mock_cache_manager.set.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_list_agents_with_pagination(self, mock_dynamodb, mock_cache_manager, mock_session_manager, sample_agent):
        """Test agent listing with pagination"""
        # Setup mocks with pagination
        mock_table = Mock()
        agent2 = sample_agent.copy()
        agent2['agent_id'] = 'test-agent-2'
        
        # First call returns page 1 with LastEvaluatedKey
        # Second call returns page 2 without LastEvaluatedKey
        mock_table.scan.side_effect = [
            {'Items': [sample_agent], 'LastEvaluatedKey': {'agent_id': 'test-agent'}},
            {'Items': [agent2]}
        ]
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock ECS client
        with patch('app.services.agent_service.boto3.client') as mock_client:
            ecs_mock = Mock()
            ecs_mock.describe_services.return_value = {
                'services': [{
                    'desiredCount': 1,
                    'runningCount': 1,
                    'createdAt': Mock(tzinfo=Mock())
                }]
            }
            mock_client.return_value = ecs_mock
            
            # Create service and test
            service = AgentService()
            result = await service.list_agents()
        
        # Assertions
        assert result['total'] == 2
        assert len(result['agents']) == 2
        assert mock_table.scan.call_count == 2
    
    @pytest.mark.asyncio
    async def test_list_agents_cache_hit(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_data = {
            'agents': [{'agent_id': 'cached-agent'}],
            'total': 1
        }
        mock_cache_manager.get.return_value = cached_data
        
        # Create service and test
        service = AgentService()
        result = await service.list_agents()
        
        # Assertions
        assert result == cached_data
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.scan.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_list_agents_error_handling(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test error handling returns empty array"""
        # Setup mock to raise exception
        mock_table = Mock()
        mock_table.scan.side_effect = Exception("DynamoDB error")
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = AgentService()
        result = await service.list_agents()
        
        # Assertions - should return empty array, not raise
        assert result['agents'] == []
        assert result['total'] == 0
        assert 'error' in result


class TestAgentServiceGetAgent:
    """Tests for get_agent() method"""
    
    @pytest.mark.asyncio
    async def test_get_agent_success(self, mock_dynamodb, mock_cache_manager, mock_session_manager, sample_agent):
        """Test successful agent retrieval"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': sample_agent}
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock ECS client
        with patch('app.services.agent_service.boto3.client') as mock_client:
            ecs_mock = Mock()
            ecs_mock.describe_services.return_value = {
                'services': [{
                    'desiredCount': 1,
                    'runningCount': 1,
                    'createdAt': Mock(tzinfo=Mock())
                }]
            }
            mock_client.return_value = ecs_mock
            
            # Create service and test
            service = AgentService()
            result = await service.get_agent('test-agent')
        
        # Assertions
        assert result is not None
        assert result['agent_id'] == 'test-agent'
        assert result['active_sessions'] == 3
        assert result['trust_score_avg'] == 95.0
        assert 'allowed_tools_count' in result
    
    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test agent not found returns None"""
        # Setup mocks
        mock_table = Mock()
        mock_table.get_item.return_value = {}  # No 'Item' key
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Create service and test
        service = AgentService()
        result = await service.get_agent('nonexistent-agent')
        
        # Assertions
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_agent_cache_hit(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_agent = {'agent_id': 'cached-agent', 'name': 'Cached Agent'}
        mock_cache_manager.get.return_value = cached_agent
        
        # Create service and test
        service = AgentService()
        result = await service.get_agent('cached-agent')
        
        # Assertions
        assert result == cached_agent
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.get_item.assert_not_called()


class TestAgentServiceGetAgentTools:
    """Tests for get_agent_tools() method"""
    
    @pytest.mark.asyncio
    async def test_get_agent_tools_success(self, mock_dynamodb, mock_s3_client, mock_cache_manager, mock_session_manager, sample_tool):
        """Test successful tools retrieval using hybrid pattern"""
        # Mock policies metadata table query
        policies_metadata_table = Mock()
        policies_metadata_table.query.return_value = {
            'Items': [{
                'policy_id': 'customer-query-agent-policy-v1',
                'agent_id': 'test-agent',
                's3_bucket': 'test-bucket',
                's3_key': 'policies/agents/test-agent/v1.0.0.yaml',
                'status': 'active'
            }]
        }

        # Mock S3 response with policy YAML
        policy_yaml = """
allowed_tools:
  - test-tool
  - test-tool-2
policies: []
"""
        mock_s3_client.get_object.return_value = {
            'Body': BytesIO(policy_yaml.encode('utf-8'))
        }

        # Mock tools table
        tools_table = Mock()
        tools_table.get_item.side_effect = [
            {'Item': sample_tool},
            {'Item': {**sample_tool, 'tool_id': 'test-tool-2'}}
        ]

        # Mock Table() to return different tables for different calls
        table_mock = Mock()
        table_mock.side_effect = [
            Mock(),  # agent_registry_table
            tools_table,  # tool_registry_table (for tool lookups)
            policies_metadata_table,  # policies_metadata_table
            Mock()  # session table (for SessionManager)
        ]
        mock_dynamodb.return_value.Table = table_mock

        # Create service and test
        service = AgentService()
        result = await service.get_agent_tools('test-agent')

        # Assertions
        assert result['agent_id'] == 'test-agent'
        assert result['total'] == 2
        assert len(result['tools']) == 2
        assert result['tools'][0]['tool_id'] == 'test-tool'
    
    @pytest.mark.asyncio
    async def test_get_agent_tools_no_policy(self, mock_dynamodb, mock_s3_client, mock_cache_manager, mock_session_manager):
        """Test agent with no policy returns empty tools"""
        # Mock policies metadata table query returning no results
        policies_metadata_table = Mock()
        policies_metadata_table.query.return_value = {'Items': []}  # No policy found

        # Mock Table() to return tables
        table_mock = Mock()
        table_mock.side_effect = [
            Mock(),  # agent_registry_table
            Mock(),  # tool_registry_table
            policies_metadata_table,  # policies_metadata_table
            Mock()  # session table (for SessionManager)
        ]
        mock_dynamodb.return_value.Table = table_mock

        # Create service and test
        service = AgentService()
        result = await service.get_agent_tools('test-agent')

        # Assertions
        assert result['agent_id'] == 'test-agent'
        assert result['total'] == 0
        assert result['tools'] == []
    
    @pytest.mark.asyncio
    async def test_get_agent_tools_missing_tool_in_registry(self, mock_dynamodb, mock_s3_client, mock_cache_manager, mock_session_manager, sample_tool):
        """Test handling of tool ID in policy but not in registry using hybrid pattern"""
        # Mock policies metadata table query
        policies_metadata_table = Mock()
        policies_metadata_table.query.return_value = {
            'Items': [{
                'policy_id': 'customer-query-agent-policy-v1',
                'agent_id': 'test-agent',
                's3_bucket': 'test-bucket',
                's3_key': 'policies/agents/test-agent/v1.0.0.yaml',
                'status': 'active'
            }]
        }

        # Mock S3 response with policy YAML including a missing tool
        policy_yaml = """
allowed_tools:
  - test-tool
  - missing-tool
policies: []
"""
        mock_s3_client.get_object.return_value = {
            'Body': BytesIO(policy_yaml.encode('utf-8'))
        }

        # Mock tools table
        tools_table = Mock()
        tools_table.get_item.side_effect = [
            {'Item': sample_tool},
            {}  # Missing tool
        ]

        # Mock Table() to return different tables for different calls
        table_mock = Mock()
        table_mock.side_effect = [
            Mock(),  # agent_registry_table
            tools_table,  # tool_registry_table
            policies_metadata_table,  # policies_metadata_table
            Mock()  # session table (for SessionManager)
        ]
        mock_dynamodb.return_value.Table = table_mock

        # Create service and test
        service = AgentService()
        result = await service.get_agent_tools('test-agent')

        # Assertions - should only return found tool
        assert result['total'] == 1
        assert len(result['tools']) == 1
        assert result['tools'][0]['tool_id'] == 'test-tool'
    
    @pytest.mark.asyncio
    async def test_get_agent_tools_cache_hit(self, mock_dynamodb, mock_cache_manager):
        """Test cache hit scenario"""
        # Setup cache to return data
        cached_tools = {
            'agent_id': 'test-agent',
            'tools': [{'tool_id': 'cached-tool'}],
            'total': 1
        }
        mock_cache_manager.get.return_value = cached_tools
        
        # Create service and test
        service = AgentService()
        result = await service.get_agent_tools('test-agent')
        
        # Assertions
        assert result == cached_tools
        # Verify DynamoDB was not called
        mock_dynamodb.return_value.Table.return_value.get_item.assert_not_called()


class TestAgentServiceHelpers:
    """Tests for helper methods"""
    
    @pytest.mark.asyncio
    async def test_get_ecs_status_running(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test ECS status for running service"""
        from datetime import datetime, timezone
        
        with patch('app.services.agent_service.boto3.client') as mock_client:
            ecs_mock = Mock()
            ecs_mock.describe_services.return_value = {
                'services': [{
                    'desiredCount': 1,
                    'runningCount': 1,
                    'createdAt': datetime.now(timezone.utc)
                }]
            }
            mock_client.return_value = ecs_mock
            
            service = AgentService()
            result = await service._get_ecs_status('test-service')
        
        assert result['status'] == 'running'
        assert result['uptime_seconds'] >= 0
    
    @pytest.mark.asyncio
    async def test_get_ecs_status_stopped(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test ECS status for stopped service"""
        with patch('app.services.agent_service.boto3.client') as mock_client:
            ecs_mock = Mock()
            ecs_mock.describe_services.return_value = {
                'services': [{
                    'desiredCount': 0,
                    'runningCount': 0
                }]
            }
            mock_client.return_value = ecs_mock
            
            service = AgentService()
            result = await service._get_ecs_status('test-service')
        
        assert result['status'] == 'stopped'
    
    @pytest.mark.asyncio
    async def test_get_ecs_status_no_service_name(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test ECS status with no service name"""
        service = AgentService()
        result = await service._get_ecs_status(None)
        
        assert result['status'] == 'unknown'
        assert result['uptime_seconds'] == 0
    
    @pytest.mark.asyncio
    async def test_get_request_counts(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Test request counts calculation"""
        service = AgentService()
        result = await service._get_request_counts('test-agent')
        
        # Should aggregate from sessions
        assert 'total' in result
        assert 'allowed' in result
        assert 'denied' in result
