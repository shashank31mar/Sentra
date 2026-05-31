"""
Overview Tab - Real-time monitoring dashboard.

Workstream 15 M4: cross-cloud activity timeline section added below the
existing panels — interleaves audit-log events across AWS / Azure / GCP for a
selected session.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import logging
from components import agent_status, security_metrics, activity_feed, rollback_panel
from config.settings import settings
from services.demo_orchestrator_client import get_demo_client
from services.security_controller_client import security_controller_client
from utils.cloud_badges import badge_for

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

    # Cross-cloud audit timeline (Workstream 15 M4)
    _render_cross_cloud_timeline()

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


@st.cache_data(ttl=15)
def _fetch_sessions_for_timeline():
    """Recent sessions to populate the cross-cloud timeline dropdown."""
    try:
        resp = security_controller_client.get_sessions(limit=50)
        return resp.get("sessions", [])
    except Exception as exc:
        logger.warning("Cross-cloud timeline session fetch failed: %s", exc)
        return []


@st.cache_data(ttl=10)
def _fetch_logs_for_session(session_id: str, lookback_hours: int = 24):
    """Audit-log entries for one session, sorted chronologically.

    Note: the controller's /v1/logs defaults to a 1-hour window when `since` is
    absent. The session list comes from a different (un-time-windowed) DDB table,
    so a session can appear in the dropdown while its audit entries are outside
    the controller's default window. We explicitly pass `since` = lookback_hours
    ago to widen the search and reduce confused "no events" pages.
    """
    if not session_id:
        return []
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat().replace("+00:00", "Z")
    try:
        resp = security_controller_client.get_logs(
            session_id=session_id, limit=200, since=since
        )
    except Exception as exc:
        logger.error("Cross-cloud timeline log fetch failed: %s", exc)
        return []
    logs = resp.get("logs", []) if isinstance(resp, dict) else []
    return sorted(logs, key=lambda log: log.get("timestamp") or "")


def _render_cross_cloud_timeline():
    """Unified session timeline interleaving events from every governed cloud.

    Workstream 15 M4 / Task 4.2 acceptance: "Selecting a session shows a
    unified timeline interleaving events from all clouds." The audit log
    already records platform + cloud_region per entry (LLD 15 §4.4, §5.4),
    so we just need to query, sort, and badge by cloud.
    """
    header_col, refresh_col = st.columns([6, 1])
    with header_col:
        st.subheader("🌐 Cross-Cloud Activity Timeline")
        st.caption("Pick a session — events from AWS, Azure, and (Phase 2) GCP appear in one chronological stream.")
    with refresh_col:
        # Issue #13 (Kiro M4 review): cache TTLs (10s logs, 15s sessions) made
        # the timeline look stale during live demos. Manual refresh clears both.
        if st.button("🔄 Refresh", key="xcloud_timeline_refresh", help="Clear cached sessions + logs"):
            _fetch_sessions_for_timeline.clear()
            _fetch_logs_for_session.clear()
            st.rerun()

    sessions = _fetch_sessions_for_timeline()
    session_ids = [s.get("session_id") for s in sessions if s.get("session_id")]

    # Lookback selector. The controller's /v1/logs default is 1h which silently
    # truncates older sessions to zero rows — surface this lever so the demo
    # presenter can widen the window when an investor picks an older session.
    lookback_label = st.radio(
        "Audit-log lookback window",
        options=["1 hour", "24 hours", "7 days", "30 days"],
        index=1,  # 24h default
        horizontal=True,
        key="xcloud_lookback",
    )
    lookback_hours = {"1 hour": 1, "24 hours": 24, "7 days": 168, "30 days": 720}[lookback_label]

    col_select, col_input = st.columns([2, 2])
    with col_select:
        if session_ids:
            chosen = st.selectbox(
                "Recent sessions",
                options=["— select —"] + session_ids,
                key="xcloud_session_select",
            )
            chosen = "" if chosen == "— select —" else chosen
        else:
            chosen = ""
            st.info("No recent sessions reported by the controller.")
    with col_input:
        manual = st.text_input(
            "…or enter a session_id",
            value="",
            key="xcloud_session_manual",
            help="Useful when the session you want isn't in the recent-sessions list.",
        )

    session_id = manual.strip() or chosen
    if not session_id:
        st.caption("Select a session or paste an ID above to render its cross-cloud timeline.")
        return

    logs = _fetch_logs_for_session(session_id, lookback_hours=lookback_hours)
    if not logs:
        # Issue #12 (Kiro M4 review): tell the user *why* a healthy-looking
        # controller might still return zero rows. Saves a triage round-trip.
        st.warning(f"No audit-log entries for session `{session_id}` in the last {lookback_label.lower()}.")
        st.caption(
            f"Try a wider lookback window above, or verify the session has had at least one "
            f"`/v1/validate` call. (Sessions can appear in the dropdown even if their audit "
            f"entries are outside the current window.)"
        )
        return

    # Cloud-distribution mini-metrics
    platforms_seen = sorted({(log.get("platform") or "unknown") for log in logs})
    metric_cols = st.columns(len(platforms_seen) + 1)
    metric_cols[0].metric("Events", len(logs))
    for idx, platform in enumerate(platforms_seen, start=1):
        count = sum(1 for log in logs if (log.get("platform") or "unknown") == platform)
        metric_cols[idx].metric(badge_for(platform), count)

    df = pd.DataFrame([
        {
            "Timestamp": log.get("timestamp"),
            "Cloud": badge_for(log.get("platform")),
            "Region": log.get("cloud_region") or "—",
            "Agent": log.get("agent_id"),
            "Tool": log.get("tool_name"),
            "Decision": log.get("decision"),
            "Latency (ms)": log.get("latency_ms"),
            "Reason": (log.get("reason") or "")[:80],
        }
        for log in logs
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)


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
