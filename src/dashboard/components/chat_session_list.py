"""
Chat Session List Component - Display chat sessions in sidebar.

Reference: LLD 04 Section 2.4
"""
import streamlit as st
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def render(sessions: List[Dict] = None, selected_session_id: Optional[str] = None) -> Optional[str]:
    """
    Render the Chat Session List sidebar.

    Args:
        sessions: List of session dictionaries (from API or mock).
                 If None, uses mock data.
        selected_session_id: Currently selected session ID.

    Returns:
        Selected session ID (or None if no selection).
    """
    if sessions is None:
        sessions = _get_mock_sessions()

    # Handle empty sessions list
    if not sessions:
        st.info("No active chat sessions. Click '+ New Chat' to start.")
        sessions = []

    st.subheader("Chat Sessions")

    # Render each session
    selected_id = selected_session_id
    for session in sessions:
        if _render_session_item(session, session['session_id'] == selected_session_id):
            selected_id = session['session_id']

    st.markdown("---")

    # New Chat button
    if st.button("➕ New Chat", use_container_width=True, key="new_chat_btn"):
        # Return special value to indicate new chat request
        return "NEW_CHAT"

    return selected_id


def _render_session_item(session: Dict, is_selected: bool) -> bool:
    """
    Render a single session item.

    Args:
        session: Session dictionary.
        is_selected: Whether this session is currently selected.

    Returns:
        True if session was clicked, False otherwise.
    """
    agent_name = session.get('agent_name', 'Unknown Agent')
    trust_score = session.get('trust_score', 0.0)
    session_id = session.get('session_id', '')

    # Determine status icon based on trust score
    if trust_score >= 80:
        status_icon = "💬"
        status_class = "normal"
    elif trust_score >= 60:
        status_icon = "⚠️"
        status_class = "warning"
    else:
        status_icon = "🔴"
        status_class = "critical"

    # Create button label
    label = f"{status_icon} {agent_name}\nTrust: {trust_score:.1f}"

    # Session button
    clicked = st.button(
        label,
        key=f"session_{session_id}",
        use_container_width=True,
        type="primary" if is_selected else "secondary",
    )

    return clicked


def _get_mock_sessions() -> List[Dict]:
    """
    Get mock session data for development.

    Returns:
        List of mock session dictionaries.
    """
    return [
        {
            'session_id': 'sess-customer-001',
            'agent_name': 'Customer Query Agent',
            'agent_id': 'customer-query-agent',
            'trust_score': 95.0,
            'message_count': 8,
            'allowed_count': 7,
            'blocked_count': 1,
            'created_at': '2025-11-27T10:30:00Z',
        },
        {
            'session_id': 'sess-payment-001',
            'agent_name': 'Payment Agent',
            'agent_id': 'payment-agent',
            'trust_score': 88.5,
            'message_count': 5,
            'allowed_count': 5,
            'blocked_count': 0,
            'created_at': '2025-11-27T10:35:00Z',
        },
        {
            'session_id': 'sess-demo-001',
            'agent_name': 'Demo Session #1',
            'agent_id': 'customer-query-agent',
            'trust_score': 65.0,
            'message_count': 12,
            'allowed_count': 8,
            'blocked_count': 4,
            'created_at': '2025-11-27T10:25:00Z',
        },
    ]
