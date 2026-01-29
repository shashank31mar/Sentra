"""
Threat Summary Component - Display threat statistics and breakdown.

Reference: LLD 04 Section 2.6
Milestone 9: Task 9.1
"""
import streamlit as st
import plotly.graph_objects as go
from typing import Dict


def render(threat_data: Dict) -> None:
    """
    Render threat summary with severity breakdown and pie chart.

    Args:
        threat_data: Dictionary with threat statistics
    """
    st.markdown("### 🛡️ Threat Summary")

    # Extract data
    total = threat_data.get('total', 0)
    critical = threat_data.get('critical', 0)
    high = threat_data.get('high', 0)
    medium = threat_data.get('medium', 0)
    low = threat_data.get('low', 0)
    threat_types = threat_data.get('threat_types', {})

    # Metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Threats", f"{total:,}")

    with col2:
        st.metric("Critical", critical, delta=None, delta_color="inverse")

    with col3:
        st.metric("High", high, delta=None, delta_color="inverse")

    with col4:
        st.metric("Medium", medium, delta=None, delta_color="normal")

    st.markdown("---")

    # Threat types pie chart
    if threat_types:
        st.markdown("**Threat Types Breakdown**")
        _render_threat_pie_chart(threat_types)
    else:
        st.info("No threat data available")


def _render_threat_pie_chart(threat_types: Dict) -> None:
    """
    Render pie chart of threat types.

    Args:
        threat_types: Dictionary of threat type counts
    """
    # Filter out zero values
    filtered_types = {k: v for k, v in threat_types.items() if v > 0}
    
    if not filtered_types:
        st.info("No threat data to display")
        return
    
    # Prepare data
    labels = list(filtered_types.keys())
    values = list(filtered_types.values())

    # Color mapping for threat types
    colors = {
        'PROMPT_INJECTION': '#FF6B6B',
        'POLICY_VIOLATION': '#FFA500',
        'DATA_EXFILTRATION': '#FF4444',
        'RATE_LIMIT': '#FFD700',
        'JAILBREAK': '#FF1493',
        'SQL_INJECTION': '#DC143C',
        'UNAUTHORIZED_TOOL': '#FF8C00',
        'SEQUENCE_VIOLATION': '#DAA520',
        'OTHER': '#999999',
    }

    pie_colors = [colors.get(label, '#999999') for label in labels]

    # Create pie chart
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=pie_colors, line=dict(color='#FFFFFF', width=2)),
        hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>',
        textposition='inside',
        textinfo='percent+label',
        hole=0.3  # Donut chart for better visibility
    )])

    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.3,
            xanchor="center",
            x=0.5
        ),
        height=350,
        margin=dict(l=20, r=20, t=20, b=60),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Clickable note
    st.caption("💡 Click on a threat type to filter in the Audit tab")


def get_mock_threat_data() -> Dict:
    """
    Get mock threat data for demo.

    Returns:
        Dictionary with mock threat statistics
    """
    return {
        'total': 23,
        'critical': 12,
        'high': 8,
        'medium': 3,
        'low': 0,
        'threat_types': {
            'PROMPT_INJECTION': 12,
            'POLICY_VIOLATION': 8,
            'DATA_EXFILTRATION': 2,
            'RATE_LIMIT': 1,
        }
    }
