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
        # Enrichment now uses ONE combined indexed-Query call (WS-21 C5/T50).
        session_mgr.get_agent_session_stats = AsyncMock(
            return_value={'active_sessions': 3, 'avg_trust_score': 95.0}
        )
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
        # Third call is the agent-policy-management T22 policy-status map scan
        # (single projected Scan of policies-metadata for active_policy_id).
        mock_table.scan.side_effect = [
            {'Items': [sample_agent], 'LastEvaluatedKey': {'agent_id': 'test-agent'}},
            {'Items': [agent2]},
            {'Items': []},
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
        # 2 agent-pagination scans + 1 policy-status-map scan (T22)
        assert mock_table.scan.call_count == 3

    @pytest.mark.asyncio
    async def test_list_agents_shows_all_clouds_hides_internal(
        self, mock_dynamodb, mock_cache_manager, mock_session_manager
    ):
        """WS-21 T05/D1/D4: all cloud providers are shown (bedrock no longer
        filtered); only visibility=internal control-plane infra is hidden."""
        agents = [
            {'agent_id': 'sentra-ext', 'name': 'A', 'status': 'active',
             'platform': 'sentra', 'cloud_provider': 'aws', 'visibility': 'external'},
            {'agent_id': 'bedrock-ext', 'name': 'B', 'status': 'active',
             'platform': 'bedrock', 'cloud_provider': 'aws', 'visibility': 'external'},
            {'agent_id': 'internal-infra', 'name': 'C', 'status': 'active',
             'platform': 'sentra', 'cloud_provider': 'aws', 'visibility': 'internal'},
        ]
        mock_table = Mock()
        mock_table.scan.return_value = {'Items': agents, 'LastEvaluatedKey': None}
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        result = await service.list_agents(enrich=False)

        ids = {a['agent_id'] for a in result['agents']}
        assert 'bedrock-ext' in ids        # bedrock no longer excluded (D1)
        assert 'sentra-ext' in ids
        assert 'internal-infra' not in ids  # visibility=internal still hidden (D4)
        assert result['total'] == 2

    @pytest.mark.asyncio
    async def test_list_agents_derives_cloud_provider_when_missing(
        self, mock_dynamodb, mock_cache_manager, mock_session_manager
    ):
        """Kombai crash fix: agents registered without cloud_provider get it
        derived from platform, so the API never emits an unmapped value."""
        agents = [
            # no cloud_provider attribute → derive from platform
            {'agent_id': 'a-bedrock', 'name': 'A', 'status': 'active',
             'platform': 'bedrock', 'visibility': 'external'},
            {'agent_id': 'a-azure', 'name': 'B', 'status': 'active',
             'platform': 'azure_foundry', 'visibility': 'external'},
        ]
        mock_table = Mock()
        mock_table.scan.return_value = {'Items': agents, 'LastEvaluatedKey': None}
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        result = await service.list_agents(enrich=False)
        by_id = {a['agent_id']: a for a in result['agents']}
        assert by_id['a-bedrock']['cloud_provider'] == 'aws'
        assert by_id['a-azure']['cloud_provider'] == 'azure'

    @pytest.mark.asyncio
    async def test_get_cloud_provider_distribution(
        self, mock_dynamodb, mock_cache_manager, mock_session_manager
    ):
        """WS-21 T21: active agents grouped by cloud_provider; pct sums to 100."""
        agents = [
            {'agent_id': 'a1', 'status': 'active', 'cloud_provider': 'aws', 'visibility': 'external'},
            {'agent_id': 'a2', 'status': 'active', 'cloud_provider': 'aws', 'visibility': 'external'},
            {'agent_id': 'a3', 'status': 'active', 'cloud_provider': 'azure', 'visibility': 'external'},
            {'agent_id': 'a4', 'status': 'inactive', 'cloud_provider': 'gcp', 'visibility': 'external'},  # not active
            {'agent_id': 'a5', 'status': 'active', 'cloud_provider': 'aws', 'visibility': 'internal'},     # internal
        ]
        mock_table = Mock()
        mock_table.scan.return_value = {'Items': agents, 'LastEvaluatedKey': None}
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        dist = await service.get_cloud_provider_distribution()

        assert dist['total_nodes'] == 3   # a1,a2,a3 (a4 inactive, a5 internal excluded)
        assert dist['clouds'] == 2        # aws, azure
        providers = {p['cloud_provider']: p for p in dist['providers']}
        assert providers['aws']['count'] == 2
        assert providers['azure']['count'] == 1
        assert sum(p['pct'] for p in dist['providers']) == 100  # remainder absorbed
    
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

        # agent-policy-management T15: get_agent_tools resolves via the binding.
        # An UNBOUND agent (no attached_policy_id) falls back to the agent-index
        # GSI query the rest of this test mocks.
        agent_registry_table = Mock()
        agent_registry_table.get_item.return_value = {'Item': {'agent_id': 'test-agent'}}

        # Dispatch Table() by name (order/count-independent): the service now
        # resolves agent_registry / policies_metadata lazily via flag-aware
        # properties, so the old positional side_effect list no longer matches.
        def _table_by_name(name):
            if 'agent-registry' in name:
                return agent_registry_table
            if 'tool-registry' in name:
                return tools_table
            if 'policies-metadata' in name:
                return policies_metadata_table
            return Mock()  # session-context etc.
        mock_dynamodb.return_value.Table = Mock(side_effect=_table_by_name)

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

        # Unbound agent → GSI fallback, which returns no policy (T15).
        agent_registry_table = Mock()
        agent_registry_table.get_item.return_value = {'Item': {'agent_id': 'test-agent'}}

        # Dispatch Table() by name (order/count-independent).
        def _table_by_name(name):
            if 'agent-registry' in name:
                return agent_registry_table
            if 'policies-metadata' in name:
                return policies_metadata_table
            return Mock()  # tool-registry / session-context
        mock_dynamodb.return_value.Table = Mock(side_effect=_table_by_name)

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

        # agent-policy-management T15: unbound agent → GSI fallback (mocked below).
        agent_registry_table = Mock()
        agent_registry_table.get_item.return_value = {'Item': {'agent_id': 'test-agent'}}

        # Dispatch Table() by name (order/count-independent) — see note above.
        def _table_by_name(name):
            if 'agent-registry' in name:
                return agent_registry_table
            if 'tool-registry' in name:
                return tools_table
            if 'policies-metadata' in name:
                return policies_metadata_table
            return Mock()  # session-context etc.
        mock_dynamodb.return_value.Table = Mock(side_effect=_table_by_name)

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


class TestAgentServicePolicyAttach:
    """attach/detach the scalar policy BINDING (agent-policy-management T21).

    Supersedes WS-21 T33's String-Set semantics: `attached_policy_id` is a scalar
    the engine reads; attach replaces atomically (no 409), detach is conditional
    on the current value.
    """

    @pytest.mark.asyncio
    async def test_attach_policy_success(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        mock_table = Mock()
        mock_table.get_item.side_effect = [
            {'Item': {'agent_id': 'a1'}},      # agent exists
            {'Item': {'policy_id': 'p1'}},     # policy exists
        ]
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        out = await service.attach_policy('a1', 'p1')

        assert out['status'] == 'attached'
        assert out['agent_id'] == 'a1' and out['policy_id'] == 'p1'
        mock_table.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_attach_policy_agent_not_found(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        mock_table = Mock()
        mock_table.get_item.side_effect = [{}]  # no agent Item
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        with pytest.raises(KeyError):
            await service.attach_policy('missing', 'p1')

    @pytest.mark.asyncio
    async def test_attach_policy_rebind_replaces(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        """Rebind-as-replace (§4.2 E): attaching when already bound is a safe
        atomic swap, NOT a 409 — the old String-Set ValueError is gone."""
        mock_table = Mock()
        mock_table.get_item.side_effect = [
            {'Item': {'agent_id': 'a1', 'attached_policy_id': 'p1'}},  # already bound to p1
            {'Item': {'policy_id': 'p2'}},                            # new policy exists
        ]
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        out = await service.attach_policy('a1', 'p2')

        assert out['status'] == 'attached'
        assert out['policy_id'] == 'p2'
        # single conditional update_item swaps the scalar binding
        mock_table.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_detach_policy_success(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': {'agent_id': 'a1', 'attached_policy_id': 'p1'}}
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        out = await service.detach_policy('a1', 'p1')

        assert out['status'] == 'detached'
        mock_table.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_detach_policy_not_attached(self, mock_dynamodb, mock_cache_manager, mock_session_manager):
        mock_table = Mock()
        mock_table.get_item.return_value = {'Item': {'agent_id': 'a1'}}  # no attached set
        mock_dynamodb.return_value.Table.return_value = mock_table

        service = AgentService()
        with pytest.raises(KeyError):
            await service.detach_policy('a1', 'p1')
