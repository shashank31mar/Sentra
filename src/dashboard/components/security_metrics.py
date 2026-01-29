"""
Security Metrics Component - Display security metrics and threat breakdown.
"""
import streamlit as st
import plotly.graph_objects as go
from typing import Dict, List
import logging

from services import security_controller_client

logger = logging.getLogger(__name__)


def _init_clients():
    """Initialize clients if not already initialized."""
    from services.security_controller_client import _get_client
    _get_client()


def render(metrics: Dict = None, threat_breakdown: List[Dict] = None, use_real_data: bool = True):
    """
    Render the Security Metrics Panel.
    
    Args:
        metrics: Dictionary with security metrics (total, blocked, allowed, block_rate).
                If None, fetches real data or uses mock data.
        threat_breakdown: List of threat type dictionaries.
                         If None, fetches real data or uses mock data.
        use_real_data: If True, fetch real data from CloudWatch.
    """
    if metrics is None:
        if use_real_data:
            metrics = _get_real_metrics()
        else:
            metrics = _get_mock_metrics()
    
    if threat_breakdown is None:
        if use_real_data:
            threat_breakdown = _get_real_threat_breakdown()
        else:
            threat_breakdown = _get_mock_threat_breakdown()
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Security Metrics")
    
    # Overview metrics with card styling
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric(
            label="Total Requests",
            value=f"{metrics['total']:,}",
            delta=None
        )
    
    with col2:
        st.metric(
            label="Blocked",
            value=f"{metrics['blocked']:,}",
            delta=None
        )
    
    col3, col4 = st.columns(2)
    
    with col3:
        st.metric(
            label="Allowed",
            value=f"{metrics['allowed']:,}",
            delta=None
        )
    
    with col4:
        st.metric(
            label="Block Rate",
            value=f"{metrics['block_rate']:.1f}%",
            delta=None
        )
    
    st.markdown("---")
    
    # Threat Types Breakdown
    st.markdown("#### Threat Types")
    
    # Pie chart (clickable - will redirect to Security tab)
    fig = _create_threat_pie_chart(threat_breakdown)
    st.plotly_chart(fig, use_container_width=True, key="threat_pie_chart")
    
    # Horizontal bars with counts
    st.markdown("#### Breakdown")
    for threat in threat_breakdown:
        _render_threat_bar(threat)
    
    # Link to Security tab
    from utils.nav import set_target_tab_in_url
    
    def _navigate_to_security():
        st.session_state["active_tab"] = "security"  # single source of truth
        st.session_state["_url_tab_applied"] = False  # allow URL to be re-applied
        set_target_tab_in_url("security")
        return  # end render cleanly
    
    st.button(
        "→ View detailed analysis in Security tab",
        key="view_security_tab_btn",
        use_container_width=True,
        on_click=_navigate_to_security
    )
    
    st.markdown('</div>', unsafe_allow_html=True)


def _create_threat_pie_chart(threat_breakdown: List[Dict]) -> go.Figure:
    """Create an interactive pie chart for threat types."""
    # Filter out zero values to avoid empty pie slices
    filtered_breakdown = [t for t in threat_breakdown if t["count"] > 0]
    
    if not filtered_breakdown:
        # Return empty figure with message if no data
        fig = go.Figure()
        fig.add_annotation(
            text="No threat data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6b7280")
        )
        fig.update_layout(
            height=300,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
        )
        return fig
    
    labels = [t["type"] for t in filtered_breakdown]
    values = [t["count"] for t in filtered_breakdown]
    colors = [t.get("color", "#667eea") for t in filtered_breakdown]
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=colors, line=dict(color='#FFFFFF', width=2)),
        hovertemplate='<b>%{label}</b><br>Count: %{value}<br>%{percent}<extra></extra>',
        textposition='inside',
        textinfo='percent+label',
        hole=0.3  # Make it a donut chart for better visibility
    )])
    
    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02
        ),
        height=300,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )
    
    return fig


def _render_threat_bar(threat: Dict):
    """Render a horizontal bar for a threat type."""
    threat_type = threat["type"]
    count = threat["count"]
    max_count = 15  # For scaling the bar
    
    # Calculate bar width percentage
    bar_width = min((count / max_count) * 100, 100)
    
    # Color based on severity
    color = threat.get("color", "#667eea")
    
    st.markdown(
        f'<div style="margin-bottom: 8px;">'
        f'  <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">'
        f'    <span style="font-size: 0.9em; font-weight: 500;">{threat_type}</span>'
        f'    <span style="font-size: 0.9em; color: #6b7280;">{count}</span>'
        f'  </div>'
        f'  <div style="background-color: #e5e7eb; border-radius: 4px; height: 8px; overflow: hidden;">'
        f'    <div style="background-color: {color}; width: {bar_width}%; height: 100%;"></div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True
    )


def _get_real_metrics() -> Dict:
    """Get real security metrics from Security Controller (cached)."""
    _init_clients()  # Ensure clients are initialized
    try:
        from services.security_controller_client import get_metrics_cached
        response = get_metrics_cached()
        
        # Extract metrics from response structure
        if not response.get('success'):
            logger.error(f"Metrics API returned error: {response.get('error')}")
            return _get_mock_metrics()
        
        metrics_data = response.get('metrics', {})
        requests = metrics_data.get('requests', {})
        
        return {
            "total": requests.get('total', 0),
            "blocked": requests.get('deny_count', 0),
            "allowed": requests.get('allow_count', 0),
            "block_rate": requests.get('deny_rate', 0.0) * 100  # Convert to percentage
        }
    except Exception as e:
        logger.error(f"Error fetching real metrics: {e}")
        return _get_mock_metrics()


def _get_real_threat_breakdown() -> List[Dict]:
    """Get real threat breakdown from Security Controller (cached)."""
    _init_clients()  # Ensure clients are initialized
    try:
        from services.security_controller_client import get_metrics_cached
        response = get_metrics_cached()
        
        # Extract metrics from response structure
        if not response.get('success'):
            logger.error(f"Metrics API returned error: {response.get('error')}")
            return []
        
        metrics_data = response.get('metrics', {})
        threats = metrics_data.get('threats', {})
        
        # Convert threats dict to list format for display
        threat_colors = {
            "PROMPT_INJECTION": "#ef4444",
            "POLICY_VIOLATION": "#f59e0b",
            "RATE_LIMIT": "#3b82f6",
            "DATA_EXFILTRATION": "#8b5cf6",
            "JAILBREAK": "#ec4899",
        }
        
        breakdown = []
        for threat_type, count in threats.items():
            breakdown.append({
                "type": threat_type.replace('_', ' ').title(),
                "count": count,
                "color": threat_colors.get(threat_type, "#6b7280")
            })
        
        # If no threats found, return empty list (not mock data)
        if not breakdown:
            return []
        
        return breakdown
    except Exception as e:
        logger.error(f"Error fetching real threat breakdown: {e}")
        return _get_mock_threat_breakdown()


def _get_mock_metrics() -> Dict:
    """Get mock security metrics."""
    return {
        "total": 1247,
        "blocked": 23,
        "allowed": 1224,
        "block_rate": 1.8,
    }


def _get_mock_threat_breakdown() -> List[Dict]:
    """Get mock threat breakdown data."""
    return [
        {
            "type": "Prompt Injection",
            "count": 12,
            "color": "#ef4444",  # Red
        },
        {
            "type": "Policy Violation",
            "count": 8,
            "color": "#f59e0b",  # Orange
        },
        {
            "type": "Rate Limit",
            "count": 3,
            "color": "#3b82f6",  # Blue
        },
    ]
