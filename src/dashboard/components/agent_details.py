"""
Agent Details Component - Display detailed agent information.
"""
import streamlit as st
from typing import Dict, Optional


def render(agent: Optional[Dict] = None):
    """
    Render the Agent Details panel.
    
    Args:
        agent: Agent dictionary with details.
               If None, shows "Select an agent" message.
    """
    if agent is None:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.info("👈 Select an agent from the list to view details")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    
    # Agent header
    st.markdown(f"### {agent.get('name', 'Unknown Agent')}")
    
    # Status badge
    status = agent.get('status', 'unknown')
    status_map = {
        "running": ("success", "🟢 Running"),
        "stopped": ("danger", "🔴 Stopped"),
        "warning": ("warning", "🟡 Warning"),
        "error": ("danger", "⚠️ Error")
    }
    badge_class, status_text = status_map.get(status, ("info", "⚫ Unknown"))
    st.markdown(f'<span class="status-badge {badge_class}">{status_text}</span>', unsafe_allow_html=True)
    
    # Metrics row with custom styling
    st.markdown('<div class="metrics-row mt-md">', unsafe_allow_html=True)
    
    # Use Streamlit columns for metrics (keeps native functionality)
    col1, col2 = st.columns(2)
    
    with col1:
        trust_score = agent.get('trust_score', 0.0)
        st.metric("Trust Score", f"{trust_score:.1f}")
    
    with col2:
        st.metric("Total Requests", f"{agent.get('requests', 0):,}")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Additional metrics
    col4, col5 = st.columns(2)
    
    with col4:
        allow_count = agent.get('allow_count', 0)
        st.metric("Allowed", f"{allow_count:,}")
    
    with col5:
        deny_count = agent.get('deny_count', 0)
        st.metric("Blocked", f"{deny_count:,}")
    
    st.markdown("---")
    
    # Description section
    st.markdown("#### Description")
    description = agent.get('description', 'No description available')
    st.markdown(f'<div class="muted">{description}</div>', unsafe_allow_html=True)
    
    # Edit Description button (non-functional for now)
    if st.button("✏️ Edit Description", key="edit_description"):
        st.info("Edit Description functionality coming soon")
    
    st.markdown('</div>', unsafe_allow_html=True)
