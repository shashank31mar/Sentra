"""
Agent List Component - Display list of agents in sidebar.

Milestone 5: Supports real API data passed from agents_tab.py.
"""
import streamlit as st
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def render(agents: List[Dict] = None, selected_agent_id: Optional[str] = None) -> Optional[str]:
    """
    Render the Agent List sidebar.
    
    This component now writes selection directly to st.session_state.selected_agent_id
    and triggers an immediate rerun so the caller doesn't need to early-return.
    
    Args:
        agents: List of agent dictionaries (from API or mock).
                If None, uses mock data.
        selected_agent_id: Currently selected agent ID.
    
    Returns:
        Selected agent ID (or None if no selection).
    """
    if agents is None:
        agents = _get_mock_agents()
    
    # Handle empty agents list
    if not agents:
        st.warning("No agents available")
        agents = _get_mock_agents()
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Agents")
    
    # Render each agent with card styling
    st.markdown('<div class="agent-list">', unsafe_allow_html=True)
    
    # Read current selected id from session_state so it's authoritative
    current_selected = st.session_state.get("selected_agent_id", selected_agent_id)
    
    for agent in agents:
        # Use helper that handles clicks internally
        _render_agent_item(agent, current_selected)
        
        # If session state changed by a click, update local var
        current_selected = st.session_state.get("selected_agent_id", current_selected)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Add Agent button (non-functional for now)
    if st.button("➕ Add Agent", use_container_width=True, key="add_agent_btn"):
        st.info("Add Agent functionality coming soon")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    return st.session_state.get("selected_agent_id")


def _render_agent_item(agent: Dict, current_selected_id: Optional[str]) -> None:
    """
    Render a single agent list item.
    
    Sets st.session_state.selected_agent_id when clicked.
    Caller handles rerun to avoid focus/timing issues.
    
    Args:
        agent: Agent dictionary.
        current_selected_id: Currently selected agent ID.
    """
    # Status dot color
    status_colors = {
        "running": "#14b8a6",
        "stopped": "#ff6b6b",
        "warning": "#f59e0b",
        "error": "#ef4444"
    }
    dot_color = status_colors.get(agent.get("status", "running"), "#7b8794")
    
    # Agent name and description
    agent_name = agent.get("name", "Unknown Agent")
    agent_desc = agent.get("description", "")[:60]
    
    # Check if selected
    is_selected = (agent['id'] == current_selected_id)
    selected_class = "selected" if is_selected else ""
    
    # Use columns so button and markup are in same visual row
    col_left, col_right = st.columns([8, 2])
    
    with col_left:
        # Render visual card (no interactive HTML buttons)
        st.markdown(f'''
            <div class="agent-item {selected_class}">
                <div class="dot" style="background:{dot_color}"></div>
                <div style="flex:1">
                    <div class="agent-name">{agent_name}</div>
                    <div class="agent-desc">{agent_desc}</div>
                </div>
            </div>
        ''', unsafe_allow_html=True)
    
    with col_right:
        # Real Streamlit button (functional)
        btn_key = f"agent_select__{agent['id']}"
        button_type = "primary" if is_selected else "secondary"
        
        # No rerun here — set session state and return
        if st.button("Select", key=btn_key, use_container_width=True, type=button_type):
            st.session_state.selected_agent_id = agent['id']


def _get_mock_agents() -> List[Dict]:
    """Get mock agent data for testing (AI agents only, not Security Controller)."""
    return [
        {
            "id": "customer-query-agent",
            "name": "Customer Query Agent",
            "status": "running",
            "description": "Handles customer data queries with read-only access",
            "uptime": "2h 34m",
            "trust_score": 95.0,
            "requests": 847,
        },
        {
            "id": "payment-agent",
            "name": "Payment Agent",
            "status": "running",
            "description": "Processes payments and refunds with write access",
            "uptime": "2h 34m",
            "trust_score": 88.5,
            "requests": 234,
        },
    ]
