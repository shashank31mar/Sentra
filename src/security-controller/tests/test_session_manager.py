"""
Unit Tests for Session Manager

Tests all session management functionality with mocked DynamoDB.
Target: >80% code coverage
"""
import pytest
import time
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from botocore.exceptions import ClientError

from app.utils.session_manager import (
    SessionManager,
    SessionNotFoundError,
    SessionUpdateError
)


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table"""
    with patch('app.utils.session_manager.boto3') as mock_boto3:
        mock_resource = Mock()
        mock_table = Mock()
        mock_boto3.resource.return_value = mock_resource
        mock_resource.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def session_manager(mock_dynamodb_table):
    """Session manager instance with mocked DynamoDB"""
    return SessionManager()


class TestGetOrCreateSession:
    """Tests for get_or_create_session method"""
    
    @pytest.mark.asyncio
    async def test_get_existing_session(self, session_manager, mock_dynamodb_table):
        """Test retrieving an existing session"""
        # Mock existing session
        mock_dynamodb_table.get_item.return_value = {
            'Item': {
                'session_id': 'sess-123',
                'user_id': 'user-1',
                'agent_id': 'agent-1',
                'trust_score': Decimal('85.5'),
                'quarantine_status': 'active',
                'consecutive_allows': 5,
                'total_requests': 100,
                'allow_count': 90,
                'deny_count': 10,
                'tool_history': [],
                'abuse_counters': {'calls_this_minute': 5, 'last_minute_reset': 12345}
            }
        }
        
        session = await session_manager.get_or_create_session('sess-123', 'user-1', 'agent-1')
        
        assert session['session_id'] == 'sess-123'
        assert session['trust_score'] == 85.5  # Converted from Decimal
        assert session['quarantine_status'] == 'active'
        mock_dynamodb_table.get_item.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_new_session(self, session_manager, mock_dynamodb_table):
        """Test creating a new session when it doesn't exist"""
        # Mock no existing session
        mock_dynamodb_table.get_item.return_value = {}
        
        session = await session_manager.get_or_create_session('sess-new', 'user-1', 'agent-1')
        
        assert session['session_id'] == 'sess-new'
        assert session['user_id'] == 'user-1'
        assert session['agent_id'] == 'agent-1'
        assert session['trust_score'] == 100.0  # Initial score
        assert session['quarantine_status'] == 'active'
        assert session['consecutive_allows'] == 0
        assert session['total_requests'] == 0
        assert session['tool_history'] == []
        
        mock_dynamodb_table.put_item.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_session_with_ttl(self, session_manager, mock_dynamodb_table):
        """Test that new session has 24-hour TTL"""
        mock_dynamodb_table.get_item.return_value = {}
        
        before_time = int(time.time())
        session = await session_manager.get_or_create_session('sess-ttl', 'user-1', 'agent-1')
        after_time = int(time.time())
        
        # TTL should be ~24 hours from now
        expected_ttl_min = before_time + (24 * 60 * 60)
        expected_ttl_max = after_time + (24 * 60 * 60)
        
        assert expected_ttl_min <= session['ttl'] <= expected_ttl_max
    
    @pytest.mark.asyncio
    async def test_get_session_dynamodb_error(self, session_manager, mock_dynamodb_table):
        """Test error handling when DynamoDB fails"""
        mock_dynamodb_table.get_item.side_effect = ClientError(
            {'Error': {'Code': 'ServiceUnavailable', 'Message': 'Service unavailable'}},
            'GetItem'
        )
        
        with pytest.raises(SessionUpdateError):
            await session_manager.get_or_create_session('sess-error', 'user-1', 'agent-1')


class TestUpdateTrustScoreDeny:
    """Tests for update_trust_score_deny method"""
    
    @pytest.mark.asyncio
    async def test_deny_decrements_trust_score(self, session_manager, mock_dynamodb_table):
        """Test that DENY decrements trust score by penalty amount"""
        # Mock two update responses (one for penalty, one for status)
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('80.0'),  # 100 - 20 (PROMPT_INJECTION penalty)
                    'consecutive_allows': 0,
                    'deny_count': 1,
                    'total_requests': 1
                }
            },
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('80.0'),
                    'quarantine_status': 'warning',
                    'consecutive_allows': 0,
                    'deny_count': 1,
                    'total_requests': 1
                }
            }
        ]
        
        session = await session_manager.update_trust_score_deny(
            'sess-123',
            'PROMPT_INJECTION',
            'Detected prompt injection'
        )
        
        assert session['trust_score'] == 80.0
        assert session['consecutive_allows'] == 0  # Reset
        assert session['quarantine_status'] == 'warning'
        assert mock_dynamodb_table.update_item.call_count == 2
    
    @pytest.mark.asyncio
    async def test_deny_with_different_penalties(self, session_manager, mock_dynamodb_table):
        """Test different violation types have different penalties"""
        test_cases = [
            ('PROMPT_INJECTION', -20),
            ('JAILBREAK', -30),
            ('POLICY_VIOLATION', -15),
            ('RATE_LIMIT_EXCEEDED', -10),
        ]
        
        for violation_type, expected_penalty in test_cases:
            mock_dynamodb_table.update_item.side_effect = [
                {
                    'Attributes': {
                        'session_id': 'sess-123',
                        'trust_score': Decimal(str(100 + expected_penalty)),
                        'consecutive_allows': 0,
                        'deny_count': 1,
                        'total_requests': 1
                    }
                },
                {
                    'Attributes': {
                        'session_id': 'sess-123',
                        'trust_score': Decimal(str(100 + expected_penalty)),
                        'quarantine_status': 'active',
                        'consecutive_allows': 0,
                        'deny_count': 1,
                        'total_requests': 1
                    }
                }
            ]
            
            session = await session_manager.update_trust_score_deny(
                'sess-123',
                violation_type,
                f'Test {violation_type}'
            )
            
            assert session['trust_score'] == 100 + expected_penalty
            mock_dynamodb_table.update_item.reset_mock()
    
    @pytest.mark.asyncio
    async def test_deny_updates_quarantine_status(self, session_manager, mock_dynamodb_table):
        """Test that quarantine status updates based on new trust score"""
        # Test suspended status (trust_score < 10)
        mock_dynamodb_table.update_item.side_effect = [
            {'Attributes': {'session_id': 'sess-123', 'trust_score': Decimal('5.0')}},
            {'Attributes': {'session_id': 'sess-123', 'trust_score': Decimal('5.0'), 'quarantine_status': 'suspended'}}
        ]
        
        session = await session_manager.update_trust_score_deny('sess-123', 'JAILBREAK', 'Test')
        assert session['quarantine_status'] == 'suspended'
        
        # Test quarantined status (10 <= trust_score < 40)
        mock_dynamodb_table.update_item.side_effect = [
            {'Attributes': {'session_id': 'sess-123', 'trust_score': Decimal('30.0')}},
            {'Attributes': {'session_id': 'sess-123', 'trust_score': Decimal('30.0'), 'quarantine_status': 'quarantined'}}
        ]
        
        session = await session_manager.update_trust_score_deny('sess-123', 'POLICY_VIOLATION', 'Test')
        assert session['quarantine_status'] == 'quarantined'
    
    @pytest.mark.asyncio
    async def test_deny_dynamodb_error(self, session_manager, mock_dynamodb_table):
        """Test error handling when DynamoDB update fails"""
        mock_dynamodb_table.update_item.side_effect = ClientError(
            {'Error': {'Code': 'ServiceUnavailable', 'Message': 'Service unavailable'}},
            'UpdateItem'
        )
        
        with pytest.raises(SessionUpdateError):
            await session_manager.update_trust_score_deny('sess-123', 'PROMPT_INJECTION', 'Test')


class TestUpdateTrustScoreAllow:
    """Tests for update_trust_score_allow method"""
    
    @pytest.mark.asyncio
    async def test_allow_increments_consecutive_allows(self, session_manager, mock_dynamodb_table):
        """Test that ALLOW increments consecutive_allows counter"""
        mock_dynamodb_table.update_item.return_value = {
            'Attributes': {
                'session_id': 'sess-123',
                'trust_score': Decimal('85.0'),
                'consecutive_allows': 5,
                'allow_count': 1,
                'total_requests': 1,
                'tool_history': [{'tool_name': 'query_customers', 'timestamp': 12345}]
            }
        }
        
        session = await session_manager.update_trust_score_allow('sess-123', 'query_customers')
        
        assert session['consecutive_allows'] == 5
        assert len(session['tool_history']) == 1
        assert session['tool_history'][0]['tool_name'] == 'query_customers'
    
    @pytest.mark.asyncio
    async def test_allow_increments_trust_score_when_threshold_reached(self, session_manager, mock_dynamodb_table):
        """Test trust score increments after reaching consecutive allows threshold"""
        # First update: consecutive_allows reaches 10 (threshold for active status)
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('75.0'),
                    'consecutive_allows': 10,
                    'tool_history': []
                }
            },
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('80.0'),  # 75 + 5 (increment for active)
                    'consecutive_allows': 0,  # Reset
                    'quarantine_status': 'active',
                    'tool_history': []
                }
            }
        ]
        
        session = await session_manager.update_trust_score_allow('sess-123', 'query_customers')
        
        assert session['trust_score'] == 80.0
        assert session['consecutive_allows'] == 0  # Reset after increment
        assert mock_dynamodb_table.update_item.call_count == 2
    
    @pytest.mark.asyncio
    async def test_allow_asymmetric_recovery_active(self, session_manager, mock_dynamodb_table):
        """Test asymmetric recovery for active status (70-100)"""
        # Active: requires 10 consecutive allows, increments by 5
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('75.0'),
                    'consecutive_allows': 10,
                    'tool_history': []
                }
            },
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('80.0'),  # +5
                    'consecutive_allows': 0,
                    'quarantine_status': 'active',
                    'tool_history': []
                }
            }
        ]
        
        session = await session_manager.update_trust_score_allow('sess-123', 'test_tool')
        assert session['trust_score'] == 80.0
    
    @pytest.mark.asyncio
    async def test_allow_asymmetric_recovery_warning(self, session_manager, mock_dynamodb_table):
        """Test asymmetric recovery for warning status (40-69)"""
        # Warning: requires 12 consecutive allows, increments by 3
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('50.0'),
                    'consecutive_allows': 12,
                    'tool_history': []
                }
            },
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('53.0'),  # +3
                    'consecutive_allows': 0,
                    'quarantine_status': 'warning',
                    'tool_history': []
                }
            }
        ]
        
        session = await session_manager.update_trust_score_allow('sess-123', 'test_tool')
        assert session['trust_score'] == 53.0
    
    @pytest.mark.asyncio
    async def test_allow_asymmetric_recovery_quarantined(self, session_manager, mock_dynamodb_table):
        """Test asymmetric recovery for quarantined status (10-39)"""
        # Quarantined: requires 15 consecutive allows, increments by 2
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('30.0'),
                    'consecutive_allows': 15,
                    'tool_history': []
                }
            },
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('32.0'),  # +2
                    'consecutive_allows': 0,
                    'quarantine_status': 'quarantined',
                    'tool_history': []
                }
            }
        ]
        
        session = await session_manager.update_trust_score_allow('sess-123', 'test_tool')
        assert session['trust_score'] == 32.0
    
    @pytest.mark.asyncio
    async def test_allow_caps_trust_score_at_100(self, session_manager, mock_dynamodb_table):
        """Test that trust score never exceeds 100"""
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('98.0'),
                    'consecutive_allows': 10,
                    'tool_history': []
                }
            },
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('100.0'),  # Capped at 100, not 103
                    'consecutive_allows': 0,
                    'quarantine_status': 'active',
                    'tool_history': []
                }
            }
        ]
        
        session = await session_manager.update_trust_score_allow('sess-123', 'test_tool')
        assert session['trust_score'] == 100.0
    
    @pytest.mark.asyncio
    async def test_allow_truncates_tool_history_to_10(self, session_manager, mock_dynamodb_table):
        """Test that tool_history is truncated to last 10 tools"""
        # Create history with 11 tools
        long_history = [{'tool_name': f'tool_{i}', 'timestamp': i} for i in range(11)]
        
        mock_dynamodb_table.update_item.side_effect = [
            {
                'Attributes': {
                    'session_id': 'sess-123',
                    'trust_score': Decimal('85.0'),
                    'consecutive_allows': 5,
                    'tool_history': long_history
                }
            },
            None  # Second update for truncation
        ]
        
        session = await session_manager.update_trust_score_allow('sess-123', 'new_tool')
        
        # Should have called update_item twice (once for allow, once for truncation)
        assert mock_dynamodb_table.update_item.call_count == 2


class TestManualQuarantine:
    """Tests for manual_quarantine method"""
    
    @pytest.mark.asyncio
    async def test_manual_quarantine_success(self, session_manager, mock_dynamodb_table):
        """Test manually quarantining a session"""
        mock_dynamodb_table.update_item.return_value = {
            'Attributes': {
                'session_id': 'sess-123',
                'quarantine_status': 'quarantined',
                'quarantine_reason': 'Suspicious behavior',
                'quarantine_operator': 'admin@sentra.com',
                'trust_score': Decimal('85.0')
            }
        }
        
        session = await session_manager.manual_quarantine(
            'sess-123',
            'Suspicious behavior',
            'admin@sentra.com'
        )
        
        assert session['quarantine_status'] == 'quarantined'
        assert session['quarantine_reason'] == 'Suspicious behavior'
        assert session['quarantine_operator'] == 'admin@sentra.com'
    
    @pytest.mark.asyncio
    async def test_manual_quarantine_session_not_found(self, session_manager, mock_dynamodb_table):
        """Test error when session doesn't exist"""
        mock_dynamodb_table.update_item.side_effect = ClientError(
            {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'Item not found'}},
            'UpdateItem'
        )
        
        with pytest.raises(SessionNotFoundError):
            await session_manager.manual_quarantine('sess-nonexistent', 'Test', 'admin')


class TestQuarantineStatusLogic:
    """Tests for quarantine status determination"""
    
    def test_get_quarantine_status_active(self, session_manager):
        """Test active status (70-100)"""
        assert session_manager._get_quarantine_status(100.0) == 'active'
        assert session_manager._get_quarantine_status(70.0) == 'active'
        assert session_manager._get_quarantine_status(85.5) == 'active'
    
    def test_get_quarantine_status_warning(self, session_manager):
        """Test warning status (40-69)"""
        assert session_manager._get_quarantine_status(69.9) == 'warning'
        assert session_manager._get_quarantine_status(40.0) == 'warning'
        assert session_manager._get_quarantine_status(55.0) == 'warning'
    
    def test_get_quarantine_status_quarantined(self, session_manager):
        """Test quarantined status (10-39)"""
        assert session_manager._get_quarantine_status(39.9) == 'quarantined'
        assert session_manager._get_quarantine_status(10.0) == 'quarantined'
        assert session_manager._get_quarantine_status(25.0) == 'quarantined'
    
    def test_get_quarantine_status_suspended(self, session_manager):
        """Test suspended status (0-9)"""
        assert session_manager._get_quarantine_status(9.9) == 'suspended'
        assert session_manager._get_quarantine_status(0.0) == 'suspended'
        assert session_manager._get_quarantine_status(5.0) == 'suspended'


class TestAsymmetricRecoveryLogic:
    """Tests for asymmetric recovery calculations"""
    
    def test_consecutive_allows_required(self, session_manager):
        """Test consecutive allows required for different trust scores"""
        # Active (70-100): 10 allows
        assert session_manager._get_consecutive_allows_required(100.0) == 10
        assert session_manager._get_consecutive_allows_required(70.0) == 10
        
        # Warning (40-69): 12 allows
        assert session_manager._get_consecutive_allows_required(69.9) == 12
        assert session_manager._get_consecutive_allows_required(40.0) == 12
        
        # Quarantined (0-39): 15 allows
        assert session_manager._get_consecutive_allows_required(39.9) == 15
        assert session_manager._get_consecutive_allows_required(0.0) == 15
    
    def test_increment_amount(self, session_manager):
        """Test increment amounts for different trust scores"""
        # Active (70-100): +5
        assert session_manager._get_increment_amount(100.0) == 5
        assert session_manager._get_increment_amount(70.0) == 5
        
        # Warning (40-69): +3
        assert session_manager._get_increment_amount(69.9) == 3
        assert session_manager._get_increment_amount(40.0) == 3
        
        # Quarantined (0-39): +2
        assert session_manager._get_increment_amount(39.9) == 2
        assert session_manager._get_increment_amount(0.0) == 2
