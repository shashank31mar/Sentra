"""
Mock Chat Service - Simulates agent chat responses for Milestone 6.

This will be replaced with real Security Controller API calls in Milestone 7.
"""
import time
import re
from typing import Dict, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MockChatService:
    """Mock chat service for demo purposes."""

    # Attack patterns that trigger DENY responses
    ATTACK_PATTERNS = [
        (r'ignore.*previous.*instructions', 'PROMPT_INJECTION', 'Prompt injection detected'),
        (r'ignore.*all.*instructions', 'PROMPT_INJECTION', 'Prompt injection detected'),
        (r'forget.*everything', 'JAILBREAK', 'Jailbreak attempt detected'),
        (r'act as.*developer', 'JAILBREAK', 'Jailbreak attempt detected'),
        (r'refund.*\$?[5-9]\d{3,}', 'POLICY_VIOLATION', 'Refund amount exceeds limit'),
        (r'refund.*\$?1\d{4,}', 'POLICY_VIOLATION', 'Refund amount exceeds limit'),
        (r'SELECT.*FROM.*WHERE', 'SQL_INJECTION', 'SQL injection attempt detected'),
        (r'<script>', 'XSS', 'Cross-site scripting attempt detected'),
        (r'\.\./', 'PATH_TRAVERSAL', 'Path traversal attempt detected'),
    ]

    def __init__(self):
        """Initialize mock chat service."""
        self.sessions = {}  # session_id -> session data
        self.messages = {}  # session_id -> list of messages

    def create_session(self, agent_id: str, agent_name: str) -> Dict:
        """
        Create a new chat session.

        Args:
            agent_id: Agent ID (e.g., 'customer-query-agent')
            agent_name: Agent display name

        Returns:
            Session dictionary
        """
        session_id = f"sess-{agent_id}-{int(time.time())}"
        session = {
            'session_id': session_id,
            'agent_id': agent_id,
            'agent_name': agent_name,
            'trust_score': 100.0,
            'initial_trust_score': 100.0,
            'message_count': 0,
            'allowed_count': 0,
            'blocked_count': 0,
            'created_at': datetime.now().isoformat() + 'Z',
        }
        self.sessions[session_id] = session
        self.messages[session_id] = []
        return session

    def send_message(self, session_id: str, user_message: str) -> Dict:
        """
        Send a message and get agent response (mock).

        Args:
            session_id: Session ID
            user_message: User's message

        Returns:
            Agent response dictionary
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self.sessions[session_id]
        messages = self.messages[session_id]

        # Add user message
        user_msg = {
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat() + 'Z',
        }
        messages.append(user_msg)

        # Simulate processing delay
        time.sleep(0.5)

        # Check for attack patterns
        decision, threat_type, reason = self._check_security(user_message)

        # Determine tool based on message content
        tool_name = self._infer_tool(user_message)

        # Generate response
        if decision == 'DENY':
            # Blocked response
            agent_msg = {
                'role': 'agent',
                'content': f'⚠️ Security violation detected!\nReason: {reason}',
                'timestamp': datetime.now().isoformat() + 'Z',
                'decision': 'DENY',
                'threat_type': threat_type,
                'tool_name': tool_name,
                'latency_ms': 12,
                'trust_delta': -20.0,
            }
            session['trust_score'] = max(0, session['trust_score'] - 20)
            session['blocked_count'] += 1
        else:
            # Allowed response
            response_content = self._generate_response(user_message, tool_name)
            agent_msg = {
                'role': 'agent',
                'content': response_content,
                'timestamp': datetime.now().isoformat() + 'Z',
                'decision': 'ALLOW',
                'tool_name': tool_name,
                'latency_ms': 45,
                'trust_delta': 0,
            }
            session['allowed_count'] += 1

        messages.append(agent_msg)
        session['message_count'] = len([m for m in messages if m['role'] == 'user'])

        return agent_msg

    def get_messages(self, session_id: str) -> List[Dict]:
        """
        Get all messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        return self.messages.get(session_id, [])

    def get_session(self, session_id: str) -> Dict:
        """
        Get session data.

        Args:
            session_id: Session ID

        Returns:
            Session dictionary
        """
        return self.sessions.get(session_id)

    def _check_security(self, message: str) -> tuple:
        """
        Check message for security threats.

        Args:
            message: User message

        Returns:
            Tuple of (decision, threat_type, reason)
        """
        message_lower = message.lower()

        for pattern, threat_type, reason in self.ATTACK_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return ('DENY', threat_type, reason)

        return ('ALLOW', None, None)

    def _infer_tool(self, message: str) -> str:
        """
        Infer which tool would be used based on message content.

        Args:
            message: User message

        Returns:
            Tool name
        """
        message_lower = message.lower()

        if 'customer' in message_lower or 'user' in message_lower:
            return 'query_customers'
        elif 'order' in message_lower:
            return 'query_orders'
        elif 'refund' in message_lower:
            return 'process_refund'
        elif 'payment' in message_lower:
            return 'process_payment'
        else:
            return 'query_data'

    def _generate_response(self, message: str, tool_name: str) -> str:
        """
        Generate mock agent response.

        Args:
            message: User message
            tool_name: Tool being used

        Returns:
            Response text
        """
        message_lower = message.lower()

        # Customer queries
        if 'customer' in message_lower:
            if 'california' in message_lower or 'ca' in message_lower:
                return "Here are the customers from CA:\n• John Doe (john@example.com)\n• Jane Smith (jane@example.com)"
            else:
                return "Found 47 customers matching your query."

        # Order queries
        elif 'order' in message_lower:
            if '#' in message:
                order_num = message.split('#')[1].split()[0]
                return f"Order #{order_num}: $50.00, Completed"
            else:
                return "Found 15 orders in the last 30 days."

        # Refund requests (normal amounts)
        elif 'refund' in message_lower:
            return "Refund processed successfully. Reference: REF-12345"

        # Payment requests
        elif 'payment' in message_lower:
            return "Payment processed: $25.00. Transaction ID: TXN-67890"

        # Generic response
        else:
            return "Request processed successfully."


# Global instance for use in dashboard
mock_chat_service = MockChatService()
