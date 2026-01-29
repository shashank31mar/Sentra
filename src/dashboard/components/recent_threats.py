"""
Recent Threats Component - Display recent security threats.

Reference: LLD 04 Section 2.6
Milestone 9: Task 9.4
"""
import streamlit as st
from typing import List, Dict
from datetime import datetime


def render(threats: List[Dict]) -> None:
    """
    Render recent threats table.

    Args:
        threats: List of threat dictionaries
    """
    st.markdown("### ⚠️ Recent Threats (Last 24h)")

    if not threats:
        st.info("No threats detected in the last 24 hours")
        return

    # Render threats table
    for threat in threats:
        _render_threat_row(threat)


def _render_threat_row(threat: Dict) -> None:
    """
    Render a single threat row.

    Args:
        threat: Threat dictionary
    """
    timestamp = threat.get('timestamp', 'N/A')
    threat_type = threat.get('threat_type', 'UNKNOWN')
    agent_id = threat.get('agent_id', 'unknown')
    matched_rule = threat.get('matched_rule', 'N/A')
    request_id = threat.get('request_id', 'N/A')
    severity = threat.get('severity', 'medium')

    # Format timestamp
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        time_str = dt.strftime('%H:%M:%S')
    except:
        time_str = timestamp

    # Threat type badge
    threat_colors = {
        'PROMPT_INJECTION': '#FF6B6B',
        'POLICY_VIOLATION': '#FFA500',
        'DATA_EXFILTRATION': '#FF4444',
        'RATE_LIMIT': '#FFD700',
        'JAILBREAK': '#FF1493',
    }
    threat_color = threat_colors.get(threat_type, '#999999')

    # Severity badge
    severity_icons = {
        'critical': '🔴',
        'high': '🟠',
        'medium': '🟡',
        'low': '🟢',
    }
    severity_icon = severity_icons.get(severity.lower(), '⚪')

    # Render row (SAFE: level 1 nesting)
    col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 2, 1])

    with col1:
        st.markdown(f"**{time_str}**")

    with col2:
        st.markdown(
            f"<span style='background-color: {threat_color}; color: white; padding: 2px 8px; border-radius: 4px;'>"
            f"{threat_type}"
            f"</span>",
            unsafe_allow_html=True,
        )

    with col3:
        st.text(f"Agent: {agent_id[:20]}")

    with col4:
        st.text(f"Rule: {matched_rule[:20]}")

    with col5:
        if st.button("👁️ View", key=f"view_threat_{request_id}", use_container_width=True):
            # Set filter for Audit tab
            st.session_state.audit_request_filter = request_id
            # Use query params to navigate (avoids session_state conflict)
            st.query_params["tab"] = "audit"
            st.rerun()

    st.markdown("---")


def get_mock_recent_threats() -> List[Dict]:
    """
    Get mock recent threats for demo.

    Returns:
        List of mock threat dictionaries
    """
    return [
        {
            'timestamp': '2025-11-27T10:45:28Z',
            'threat_type': 'PROMPT_INJECTION',
            'agent_id': 'payment-agent',
            'matched_rule': 'Prompt Injection - Basic',
            'request_id': 'req-abc-002',
            'severity': 'high',
        },
        {
            'timestamp': '2025-11-27T10:42:15Z',
            'threat_type': 'POLICY_VIOLATION',
            'agent_id': 'payment-agent',
            'matched_rule': 'Refund Limit Policy',
            'request_id': 'req-abc-005',
            'severity': 'medium',
        },
        {
            'timestamp': '2025-11-27T10:38:30Z',
            'threat_type': 'DATA_EXFILTRATION',
            'agent_id': 'customer-query-agent',
            'matched_rule': 'Data Exfiltration',
            'request_id': 'req-abc-007',
            'severity': 'high',
        },
    ]
