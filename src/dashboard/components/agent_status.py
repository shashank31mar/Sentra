"""
Agent Status Component - Display agent health and status.
"""
import streamlit as st
from typing import Dict, List
import logging

from services import security_controller_client

logger = logging.getLogger(__name__)


def _init_clients():
    """Initialize clients if not already initialized."""
    from services.security_controller_client import _get_client
    _get_client()


def render(agents: List[Dict] = None, use_real_data: bool = True):
    """
    Render the Agent Status Panel.
    
    Args:
        agents: List of agent dictionaries with status info.
                If None, fetches real data or uses mock data.
        use_real_data: If True, fetch real data from APIs.
    """
    if agents is None:
        if use_real_data:
            agents = _get_real_agents()
        else:
            agents = _get_mock_agents()
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Agent Status")
    
    # Create columns for each agent
    cols = st.columns(len(agents))
    
    for idx, agent in enumerate(agents):
        with cols[idx]:
            _render_agent_card(agent)
    
    st.markdown('</div>', unsafe_allow_html=True)


def _render_agent_card(agent: Dict):
    """Render a single agent status card with styling."""
    # Status badge class
    status_badge = agent.get("badge", "Normal")
    badge_class_map = {
        "Normal": "success",
        "Warning": "warning",
        "Critical": "danger",
        "Quarantined": "info",
        "Healthy": "success",
    }
    badge_class = badge_class_map.get(status_badge, "info")
    
    # Agent name with status badge
    st.markdown(f"### {agent['name']}")
    st.markdown(f'<span class="status-badge {badge_class}">{status_badge}</span>', unsafe_allow_html=True)
    
    # Metrics in a container
    with st.container():
        # Uptime
        st.metric(
            label="Uptime",
            value=agent["uptime"],
            delta=None
        )
        
        # Trust Score with color indicator
        trust_score = agent["trust_score"]
        st.metric(
            label="Trust Score",
            value=f"{trust_score:.1f}",
            delta=None
        )
        
        # Visual trust score indicator
        trust_color = _get_trust_color(trust_score)
        st.markdown(
            f'<div style="width: 100%; height: 6px; background: #e5e7eb; border-radius: 3px; margin-top: 4px;">'
            f'  <div style="width: {trust_score}%; height: 100%; background: {trust_color}; border-radius: 3px;"></div>'
            f'</div>',
            unsafe_allow_html=True
        )


def _get_trust_color(score: float) -> str:
    """Get color based on trust score."""
    if score >= 90:
        return "#10b981"  # Green
    elif score >= 70:
        return "#f59e0b"  # Yellow
    else:
        return "#ef4444"  # Red


def _get_badge_color(badge: str) -> str:
    """Get color based on badge status."""
    badge_colors = {
        "Normal": "#10b981",      # Green
        "Warning": "#f59e0b",     # Yellow
        "Critical": "#ef4444",    # Red
        "Quarantined": "#6b7280", # Gray
    }
    return badge_colors.get(badge, "#6b7280")


def _get_real_agents() -> List[Dict]:
    """Get real agent data from Security Controller API with enrichment."""
    _init_clients()
    
    # Fetch agents with enrichment (includes uptime, trust scores, etc.)
    # This is slower but provides complete data for the status panel
    try:
        agents_response = security_controller_client.get_agents_enriched()
        agent_list = agents_response.get('agents', [])
    except Exception as e:
        logger.error(f"Error fetching enriched agents: {e}")
        return _get_mock_agents()
    
    if not agent_list:
        logger.warning("No agents returned from API, using mock data")
        return _get_mock_agents()
    
    # Transform to display format
    agents = []
    for agent in agent_list:
        agent_name = agent.get('name', agent.get('agent_id', 'Unknown'))
        
        # Get uptime from enriched data
        uptime_seconds = agent.get('uptime_seconds', 0)
        uptime = _format_uptime(uptime_seconds)
        
        # Get trust score
        trust_score = agent.get('trust_score_avg', 100.0)
        
        # Determine status and badge
        status = agent.get('status', 'unknown')
        if status == 'running':
            badge = 'Normal'
        elif status == 'starting':
            badge = 'Warning'
        else:
            badge = 'Critical'
        
        agents.append({
            "name": agent_name,
            "status": status,
            "uptime": uptime,
            "trust_score": float(trust_score),
            "badge": badge,
            "requests": agent.get('requests_total', 0),
        })
    
    return agents if agents else _get_mock_agents()


def _format_uptime(seconds: int) -> str:
    """Format uptime seconds to human-readable string."""
    if seconds <= 0:
        return "N/A"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 24:
        days = hours // 24
        hours = hours % 24
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def _get_mock_agents() -> List[Dict]:
    """Get mock agent data for testing (external agents only)."""
    return [
        {
            "name": "Customer Query Agent",
            "status": "running",
            "uptime": "2h 34m",
            "trust_score": 95.0,
            "badge": "Normal",
            "requests": 847,
        },
        {
            "name": "Payment Agent",
            "status": "running",
            "uptime": "2h 34m",
            "trust_score": 88.5,
            "badge": "Normal",
            "requests": 234,
        },
        {
            "name": "Bedrock Secured Agent",
            "status": "running",
            "uptime": "1h 15m",
            "trust_score": 92.0,
            "badge": "Normal",
            "requests": 156,
        },
        {
            "name": "Bedrock Unsecured Agent",
            "status": "running",
            "uptime": "1h 15m",
            "trust_score": 0.0,
            "badge": "Warning",
            "requests": 89,
        },
    ]
