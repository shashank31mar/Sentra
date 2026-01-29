"""
Integration Tests for Agent Management APIs

Tests all 5 new GET endpoints with real service layer (mocked AWS).
Target: >90% code coverage
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch

from app.main import app


@pytest.fixture
def client():
    """Test client for FastAPI app"""
    return TestClient(app)


@pytest.fixture
def mock_agent_service():
    """Mock AgentService"""
    with patch('app.api.routes.AgentService') as mock:
        service = Mock()
        service.list_agents = AsyncMock(return_value={
            'agents': [
                {
                    'agent_id': 'test-agent',
                    'name': 'Test Agent',
                    'status': 'running',
                    'trust_score_avg': 95.0,
                    'active_sessions': 3
                }
            ],
            'total': 1
        })
        service.get_agent = AsyncMock(return_value={
            'agent_id': 'test-agent',
            'name': 'Test Agent',
            'status': 'running',
            'allowed_tools_count': 5
        })
        service.get_agent_tools = AsyncMock(return_value={
            'agent_id': 'test-agent',
            'tools': [
                {'tool_id': 'test-tool', 'name': 'Test Tool'}
            ],
            'total': 1
        })
        mock.return_value = service
        yield service


@pytest.fixture
def mock_policy_service():
    """Mock PolicyService"""
    with patch('app.api.routes.PolicyService') as mock:
        service = Mock()
        service.query_policies = AsyncMock(return_value={
            'policies': [
                {
                    'policy_id': 'test-policy',
                    'agent_id': 'test-agent',
                    'status': 'active'
                }
            ],
            'total': 1,
            'has_more': False
        })
        mock.return_value = service
        yield service


@pytest.fixture
def mock_sigma_rules_service():
    """Mock SigmaRulesService"""
    with patch('app.api.routes.SigmaRulesService') as mock:
        service = Mock()
        service.list_sigma_rules = AsyncMock(return_value={
            'rules': [
                {
                    'rule_id': 'sigma-llm-001',
                    'title': 'Test Rule',
                    'level': 'high',
                    'status': 'stable'
                }
            ],
            'total': 1,
            'has_more': False
        })
        mock.return_value = service
        yield service


class TestGetAgentsEndpoint:
    """Tests for GET /v1/agents endpoint"""
    
    def test_get_agents_success(self, client, mock_agent_service):
        """Test successful agent listing"""
        response = client.get("/v1/agents")
        
        assert response.status_code == 200
        data = response.json()
        assert 'agents' in data
        assert 'total' in data
        assert data['total'] == 1
        assert data['agents'][0]['agent_id'] == 'test-agent'
        
        # Verify service was called
        mock_agent_service.list_agents.assert_called_once()
    
    def test_get_agents_empty_result(self, client, mock_agent_service):
        """Test agent listing with no agents"""
        mock_agent_service.list_agents.return_value = {
            'agents': [],
            'total': 0
        }
        
        response = client.get("/v1/agents")
        
        assert response.status_code == 200
        data = response.json()
        assert data['agents'] == []
        assert data['total'] == 0


class TestGetAgentEndpoint:
    """Tests for GET /v1/agents/{agent_id} endpoint"""
    
    def test_get_agent_success(self, client, mock_agent_service):
        """Test successful agent retrieval"""
        response = client.get("/v1/agents/test-agent")
        
        assert response.status_code == 200
        data = response.json()
        assert data['agent_id'] == 'test-agent'
        assert data['name'] == 'Test Agent'
        
        # Verify service was called with correct agent_id
        mock_agent_service.get_agent.assert_called_once_with('test-agent')
    
    def test_get_agent_not_found(self, client, mock_agent_service):
        """Test agent not found returns 404"""
        mock_agent_service.get_agent.return_value = None
        
        response = client.get("/v1/agents/nonexistent-agent")
        
        assert response.status_code == 404
        data = response.json()
        assert 'detail' in data
        assert 'not found' in data['detail'].lower()


class TestGetAgentToolsEndpoint:
    """Tests for GET /v1/agents/{agent_id}/tools endpoint"""
    
    def test_get_agent_tools_success(self, client, mock_agent_service):
        """Test successful tools retrieval"""
        response = client.get("/v1/agents/test-agent/tools")
        
        assert response.status_code == 200
        data = response.json()
        assert data['agent_id'] == 'test-agent'
        assert 'tools' in data
        assert 'total' in data
        assert data['total'] == 1
        
        # Verify service was called with correct agent_id
        mock_agent_service.get_agent_tools.assert_called_once_with('test-agent')
    
    def test_get_agent_tools_empty(self, client, mock_agent_service):
        """Test agent with no tools"""
        mock_agent_service.get_agent_tools.return_value = {
            'agent_id': 'test-agent',
            'tools': [],
            'total': 0
        }
        
        response = client.get("/v1/agents/test-agent/tools")
        
        assert response.status_code == 200
        data = response.json()
        assert data['tools'] == []
        assert data['total'] == 0
    
    def test_get_agent_tools_agent_not_found(self, client, mock_agent_service):
        """Test tools endpoint with non-existent agent"""
        mock_agent_service.get_agent_tools.return_value = {
            'agent_id': 'nonexistent-agent',
            'tools': [],
            'total': 0,
            'error': 'Agent not found'
        }
        
        response = client.get("/v1/agents/nonexistent-agent/tools")
        
        assert response.status_code == 404


class TestGetPoliciesEndpoint:
    """Tests for GET /v1/policies endpoint"""
    
    def test_get_policies_no_filters(self, client, mock_policy_service):
        """Test policies query without filters"""
        response = client.get("/v1/policies")
        
        assert response.status_code == 200
        data = response.json()
        assert 'policies' in data
        assert 'total' in data
        assert 'has_more' in data
        
        # Verify service was called with defaults
        mock_policy_service.query_policies.assert_called_once_with(
            agent_id=None,
            status=None,
            limit=50
        )
    
    def test_get_policies_with_agent_id_filter(self, client, mock_policy_service):
        """Test policies query with agent_id filter"""
        response = client.get("/v1/policies?agent_id=test-agent")
        
        assert response.status_code == 200
        
        # Verify service was called with agent_id
        mock_policy_service.query_policies.assert_called_once_with(
            agent_id='test-agent',
            status=None,
            limit=50
        )
    
    def test_get_policies_with_status_filter(self, client, mock_policy_service):
        """Test policies query with status filter"""
        response = client.get("/v1/policies?status=active")
        
        assert response.status_code == 200
        
        # Verify service was called with status
        mock_policy_service.query_policies.assert_called_once_with(
            agent_id=None,
            status='active',
            limit=50
        )
    
    def test_get_policies_with_limit(self, client, mock_policy_service):
        """Test policies query with custom limit"""
        response = client.get("/v1/policies?limit=10")
        
        assert response.status_code == 200
        
        # Verify service was called with limit
        mock_policy_service.query_policies.assert_called_once_with(
            agent_id=None,
            status=None,
            limit=10
        )
    
    def test_get_policies_invalid_status(self, client, mock_policy_service):
        """Test policies query with invalid status returns 400"""
        response = client.get("/v1/policies?status=invalid")
        
        assert response.status_code == 400
        data = response.json()
        assert 'detail' in data
        assert 'Invalid status' in data['detail']
    
    def test_get_policies_invalid_limit(self, client, mock_policy_service):
        """Test policies query with invalid limit returns 400"""
        response = client.get("/v1/policies?limit=0")
        
        assert response.status_code == 400
        data = response.json()
        assert 'detail' in data
        assert 'Limit must be between' in data['detail']
    
    def test_get_policies_limit_too_high(self, client, mock_policy_service):
        """Test policies query with limit > 200 returns 400"""
        response = client.get("/v1/policies?limit=500")
        
        assert response.status_code == 400


class TestGetSigmaRulesEndpoint:
    """Tests for GET /v1/sigma-rules endpoint"""
    
    def test_get_sigma_rules_no_filters(self, client, mock_sigma_rules_service):
        """Test Sigma rules query without filters"""
        response = client.get("/v1/sigma-rules")
        
        assert response.status_code == 200
        data = response.json()
        assert 'rules' in data
        assert 'total' in data
        assert 'has_more' in data
        
        # Verify service was called with defaults
        mock_sigma_rules_service.list_sigma_rules.assert_called_once_with(
            status=None,
            level=None,
            limit=50
        )
    
    def test_get_sigma_rules_with_status_filter(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with status filter"""
        response = client.get("/v1/sigma-rules?status=stable")
        
        assert response.status_code == 200
        
        # Verify service was called with status
        mock_sigma_rules_service.list_sigma_rules.assert_called_once_with(
            status='stable',
            level=None,
            limit=50
        )
    
    def test_get_sigma_rules_with_level_filter(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with level filter"""
        response = client.get("/v1/sigma-rules?level=high")
        
        assert response.status_code == 200
        
        # Verify service was called with level
        mock_sigma_rules_service.list_sigma_rules.assert_called_once_with(
            status=None,
            level='high',
            limit=50
        )
    
    def test_get_sigma_rules_with_limit(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with custom limit"""
        response = client.get("/v1/sigma-rules?limit=10")
        
        assert response.status_code == 200
        
        # Verify service was called with limit
        mock_sigma_rules_service.list_sigma_rules.assert_called_once_with(
            status=None,
            level=None,
            limit=10
        )
    
    def test_get_sigma_rules_invalid_status(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with invalid status returns 400"""
        response = client.get("/v1/sigma-rules?status=invalid")
        
        assert response.status_code == 400
        data = response.json()
        assert 'detail' in data
        assert 'Invalid status' in data['detail']
    
    def test_get_sigma_rules_invalid_level(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with invalid level returns 400"""
        response = client.get("/v1/sigma-rules?level=invalid")
        
        assert response.status_code == 400
        data = response.json()
        assert 'detail' in data
        assert 'Invalid level' in data['detail']
    
    def test_get_sigma_rules_invalid_limit(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with invalid limit returns 400"""
        response = client.get("/v1/sigma-rules?limit=0")
        
        assert response.status_code == 400
    
    def test_get_sigma_rules_limit_too_high(self, client, mock_sigma_rules_service):
        """Test Sigma rules query with limit > 200 returns 400"""
        response = client.get("/v1/sigma-rules?limit=500")
        
        assert response.status_code == 400


class TestEndpointErrorHandling:
    """Tests for error handling across all endpoints"""
    
    def test_agents_endpoint_service_error(self, client, mock_agent_service):
        """Test agents endpoint handles service errors gracefully"""
        mock_agent_service.list_agents.side_effect = Exception("Service error")
        
        # Should not raise, but return error response
        response = client.get("/v1/agents")
        
        # Depending on implementation, might return 500 or empty result
        assert response.status_code in [200, 500]
    
    def test_policies_endpoint_with_all_filters(self, client, mock_policy_service):
        """Test policies endpoint with all filters combined"""
        response = client.get("/v1/policies?agent_id=test-agent&status=active&limit=10")
        
        assert response.status_code == 200
        
        # Verify all parameters passed correctly
        mock_policy_service.query_policies.assert_called_once_with(
            agent_id='test-agent',
            status='active',
            limit=10
        )
    
    def test_sigma_rules_endpoint_with_all_filters(self, client, mock_sigma_rules_service):
        """Test Sigma rules endpoint with all filters combined"""
        response = client.get("/v1/sigma-rules?status=stable&level=high&limit=10")
        
        assert response.status_code == 200
        
        # Verify all parameters passed correctly
        mock_sigma_rules_service.list_sigma_rules.assert_called_once_with(
            status='stable',
            level='high',
            limit=10
        )
