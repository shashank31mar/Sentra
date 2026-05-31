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
    
    st.markdown("---")

    # Description section
    st.markdown("#### Description")
    description = agent.get('description', 'No description available')
    st.markdown(f'<div class="muted">{description}</div>', unsafe_allow_html=True)
    
    # Edit Description button (non-functional for now)
    if st.button("✏️ Edit Description", key="edit_description"):
        st.info("Edit Description functionality coming soon")
    
    st.markdown('</div>', unsafe_allow_html=True)
