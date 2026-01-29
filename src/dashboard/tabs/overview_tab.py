"""
Overview Tab - Real-time monitoring dashboard.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import logging
from components import agent_status, security_metrics, activity_feed, rollback_panel
from config.settings import settings
from services.demo_orchestrator_client import get_demo_client

logger = logging.getLogger(__name__)


def render():
    """Render the Overview tab with auto-refresh."""
    # Check if we should use real data (can be toggled for testing)
    use_real_data = st.session_state.get('use_real_data', True)
    
    # Add toggle for testing
    with st.sidebar:
        st.markdown("### Data Source")
        use_real_data = st.checkbox(
            "Use Real Data",
            value=use_real_data,
            help="Toggle between real API data and mock data",
            key="overview_use_real_data"
        )
        st.session_state.use_real_data = use_real_data
        
        if not use_real_data:
            st.warning("Using mock data for testing")
    
    # Agent Status Panel (top)
    agent_status.render(use_real_data=use_real_data)
    
    st.markdown("---")
    
    # Two-column layout: Security Metrics (left) + Activity Feed (right)
    col1, col2 = st.columns([1, 2])
    
    with col1:
        security_metrics.render(use_real_data=use_real_data)
    
    with col2:
        activity_feed.render(limit=5, use_real_data=use_real_data)
    
    st.markdown("---")
    
    # Rollback Management Panel (bottom)
    rollback_panel.render(limit=5, use_real_data=use_real_data)
    
    st.markdown("---")
    
    # Bedrock Security Comparison (new section)
    _render_bedrock_comparison()
    
    # Auto-refresh logic (1 second interval)
    # REMOVED st.rerun() - use Streamlit's native fragment rerun instead
    # This prevents SessionInfo race condition in lazy-loaded tabs
    if st.session_state.get('auto_refresh', True):
        # Use st.empty() placeholder pattern for auto-refresh
        # This is more stable than st.rerun() in lazy tabs
        pass  # Auto-refresh will be handled by user interaction or fragment API


@st.cache_data(ttl=60)
def _fetch_comparison_data():
    """Fetch comparison data with caching (60s TTL for overview)"""
    try:
        client = get_demo_client()
        data = client.get_comparison(hours=24)
        return data.get("comparison", {})
    except Exception as e:
        logger.warning(f"Could not load comparison data: {e}")
        return None


def _render_bedrock_comparison():
    """Add Bedrock comparison section to Overview tab"""
    st.subheader("🔐 Bedrock Agent Security Comparison (24h)")
    st.caption("Compare security posture between secured and unsecured Bedrock agents")
    
    with st.spinner("Loading comparison data..."):
        comparison = _fetch_comparison_data()
    
    if comparison is None:
        st.info("📭 Demo comparison data unavailable. Start demo scenarios to generate data.")
        return
    
    # Check if any data
    total_requests = sum(
        comparison.get(agent_type, {}).get("total", 0)
        for agent_type in ["self_hosted", "bedrock_secured", "bedrock_unsecured"]
    )
    
    if total_requests == 0:
        st.info("📊 No demo data yet. Run demo scenarios to generate comparison data.")
        return
    
    st.caption(f"Analyzing {total_requests} requests from the last 24 hours")
    
    # Comparison table
    _render_comparison_table(comparison)
    
    st.markdown("---")
    
    # Dual pie charts
    st.caption("Visual comparison of security decisions")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**⚠️ Bedrock Unsecured**")
        with st.container():
            _render_pie_chart(
                comparison.get("bedrock_unsecured", {}),
                is_unsecured=True,
                chart_key="overview_pie_unsecured"
            )
        st.caption("⚠️ High Risk - No Security Layer")
    
    with col2:
        st.markdown("**✅ Bedrock Secured (Sentra)**")
        with st.container():
            _render_pie_chart(
                comparison.get("bedrock_secured", {}),
                is_unsecured=False,
                chart_key="overview_pie_secured"
            )
        st.caption("✅ Protected by Sentra")


def _render_comparison_table(data: dict):
    """Render comparison table"""
    self_hosted = data.get("self_hosted", {})
    bedrock_secured = data.get("bedrock_secured", {})
    bedrock_unsecured = data.get("bedrock_unsecured", {})
    
    # Calculate security scores
    sh_score = 100 - self_hosted.get("allowed_pct", 0)
    bs_score = 100 - bedrock_secured.get("allowed_pct", 0)
    bu_score = 100 - bedrock_unsecured.get("allowed_pct", 0)
    
    # Score color indicators
    sh_indicator = "🟢" if sh_score > 80 else ("🟡" if sh_score > 50 else "🔴")
    bs_indicator = "🟢" if bs_score > 80 else ("🟡" if bs_score > 50 else "🔴")
    bu_indicator = "🟢" if bu_score > 80 else ("🟡" if bu_score > 50 else "🔴")
    
    df = pd.DataFrame({
        "Agent Type": [
            "Self-Hosted Agents",
            "Bedrock Secured (Sentra)",
            "⚠️ Bedrock Unsecured"
        ],
        "Total": [
            self_hosted.get("total", 0),
            bedrock_secured.get("total", 0),
            bedrock_unsecured.get("total", 0)
        ],
        "Allowed": [
            f"{self_hosted.get('allowed', 0)} ({self_hosted.get('allowed_pct', 0)}%)",
            f"{bedrock_secured.get('allowed', 0)} ({bedrock_secured.get('allowed_pct', 0)}%)",
            f"{bedrock_unsecured.get('allowed', 0)} ({bedrock_unsecured.get('allowed_pct', 0)}%)"
        ],
        "Denied": [
            f"{self_hosted.get('denied', 0)} ({self_hosted.get('denied_pct', 0)}%)",
            f"{bedrock_secured.get('denied', 0)} ({bedrock_secured.get('denied_pct', 0)}%)",
            f"{bedrock_unsecured.get('denied', 0)} ({bedrock_unsecured.get('denied_pct', 0)}%)"
        ],
        "Security Score": [
            f"{sh_indicator} {sh_score:.1f}%",
            f"{bs_indicator} {bs_score:.1f}%",
            f"{bu_indicator} {bu_score:.1f}%"
        ]
    })
    
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_pie_chart(metrics: dict, is_unsecured: bool, chart_key: str):
    """Render pie chart for agent type"""
    total = metrics.get("total", 0)
    
    if total == 0:
        st.info("No data yet")
        return
    
    denied = metrics.get("denied", 0)
    allowed = metrics.get("allowed", 0)
    rollback = metrics.get("rollback", 0)
    
    # Build labels and values, filtering zeros
    labels = []
    values = []
    colors = []
    
    if is_unsecured:
        # Unsecured: Red for allowed (bad), yellow for denied
        color_map = {
            "Denied": "#ffaa00",    # Yellow (neutral)
            "Allowed": "#ff4444",   # Red (bad)
            "Rollback": "#4444ff"   # Blue
        }
    else:
        # Secured: Green for denied (good), yellow for allowed
        color_map = {
            "Denied": "#44ff44",    # Green (good)
            "Allowed": "#ffaa00",   # Yellow (warning)
            "Rollback": "#4444ff"   # Blue
        }
    
    if denied > 0:
        labels.append("Denied")
        values.append(denied)
        colors.append(color_map["Denied"])
    
    if allowed > 0:
        labels.append("Allowed")
        values.append(allowed)
        colors.append(color_map["Allowed"])
    
    if rollback > 0:
        labels.append("Rollback")
        values.append(rollback)
        colors.append(color_map["Rollback"])
    
    if not values:
        st.info("No data")
        return
    
    # Create pie chart
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=colors),
        hole=0.3,
        textinfo="label+percent",
        textposition="inside"
    )])
    
    fig.update_layout(
        showlegend=True,
        height=300,
        margin=dict(t=0, b=0, l=0, r=0)
    )
    
    st.plotly_chart(fig, use_container_width=True, key=chart_key)
