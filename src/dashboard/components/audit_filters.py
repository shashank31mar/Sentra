"""
Audit Filters Component - Filter controls for audit log.

Reference: LLD 04 Section 2.5
Milestone 8: Task 8.1
"""
import streamlit as st
from typing import Dict, List
from datetime import datetime, timedelta
import logging

from services import security_controller_client

logger = logging.getLogger(__name__)


@st.cache_data(ttl=60)
def _get_agent_options() -> List[str]:
    """Fetch agent IDs from API (cached for 60s)."""
    try:
        response = security_controller_client.get_agents()
        agents = response.get('agents', [])
        agent_ids = [agent.get('agent_id') for agent in agents if agent.get('agent_id')]
        return ['All'] + sorted(agent_ids)
    except Exception as e:
        logger.warning(f"Could not fetch agents for filter: {e}")
        # Fallback to known agents
        return ['All', 'customer-query-agent', 'payment-agent', 'bedrock-secured', 'bedrock-unsecured']


def render() -> Dict:
    """
    Render audit filters and return selected filter values.

    Returns:
        Dictionary with filter values: {
            'time_range': str,
            'agent_id': str,
            'decision': str,
            'threat_type': str,
            'session_id': str,
            'request_id': str,
        }
    """
    st.markdown("### 🔍 Filters")

    # Initialize filter state
    if 'audit_filters' not in st.session_state:
        st.session_state.audit_filters = {
            'time_range': 'Last 24h',
            'agent_id': 'All',
            'decision': 'All',
            'threat_type': 'All',
            'session_id': '',
            'request_id': '',
        }

    # Check if filters were pre-set from other tabs
    if 'audit_agent_filter' in st.session_state and st.session_state.audit_agent_filter:
        st.session_state.audit_filters['agent_id'] = st.session_state.audit_agent_filter
        st.session_state.audit_agent_filter = None  # Clear after applying

    if 'audit_session_filter' in st.session_state and st.session_state.audit_session_filter:
        st.session_state.audit_filters['session_id'] = st.session_state.audit_session_filter
        st.session_state.audit_session_filter = None  # Clear after applying

    # Filter inputs in columns
    col1, col2, col3 = st.columns(3)

    with col1:
        time_range = st.selectbox(
            "Time Range",
            options=['Last 1h', 'Last 6h', 'Last 24h', 'Last 7d', 'Last 30d', 'Custom'],
            index=['Last 1h', 'Last 6h', 'Last 24h', 'Last 7d', 'Last 30d', 'Custom'].index(
                st.session_state.audit_filters['time_range']
            ),
            key='filter_time_range',
        )

    with col2:
        # Fetch agent options dynamically from API
        agent_options = _get_agent_options()
        current_agent = st.session_state.audit_filters['agent_id']
        agent_id = st.selectbox(
            "Agent",
            options=agent_options,
            index=agent_options.index(current_agent) if current_agent in agent_options else 0,
            key='filter_agent_id',
        )

    with col3:
        decision = st.selectbox(
            "Decision",
            options=['All', 'ALLOW', 'DENY'],
            index=['All', 'ALLOW', 'DENY'].index(st.session_state.audit_filters['decision']),
            key='filter_decision',
        )

    # Second row of filters
    col4, col5, col6 = st.columns(3)

    with col4:
        threat_type = st.selectbox(
            "Threat Type",
            options=['All', 'PROMPT_INJECTION', 'POLICY_VIOLATION', 'DATA_EXFILTRATION', 'RATE_LIMIT'],
            index=0,
            key='filter_threat_type',
        )

    with col5:
        session_id = st.text_input(
            "Session ID",
            value=st.session_state.audit_filters['session_id'],
            placeholder="sess-xyz-123",
            key='filter_session_id',
        )

    with col6:
        request_id = st.text_input(
            "Request ID",
            value=st.session_state.audit_filters['request_id'],
            placeholder="req-abc-456",
            key='filter_request_id',
        )

    # Action buttons
    col_btn1, col_btn2, col_btn3, col_btn4, col_spacer = st.columns([1, 1, 1.2, 1.2, 3])

    with col_btn1:
        apply_clicked = st.button("✅ Apply", use_container_width=True, type="primary")

    with col_btn2:
        reset_clicked = st.button("🔄 Reset", use_container_width=True)

    with col_btn3:
        export_csv_clicked = st.button("📥 Export CSV", use_container_width=True)

    with col_btn4:
        export_json_clicked = st.button("📥 Export JSON", use_container_width=True)

    # Handle button clicks
    if apply_clicked:
        st.session_state.audit_filters = {
            'time_range': time_range,
            'agent_id': agent_id,
            'decision': decision,
            'threat_type': threat_type,
            'session_id': session_id,
            'request_id': request_id,
        }
        st.success("✓ Filters applied")

    if reset_clicked:
        st.session_state.audit_filters = {
            'time_range': 'Last 24h',
            'agent_id': 'All',
            'decision': 'All',
            'threat_type': 'All',
            'session_id': '',
            'request_id': '',
        }
        # No st.rerun() needed - filters will reset on next render

    if export_csv_clicked:
        st.session_state.export_format = 'CSV'
        st.session_state.show_export_dialog = True

    if export_json_clicked:
        st.session_state.export_format = 'JSON'
        st.session_state.show_export_dialog = True

    st.markdown("---")

    return st.session_state.audit_filters
