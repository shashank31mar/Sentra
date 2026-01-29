"""
Agent Tools Component - Display and manage agent's allowed tools.

Milestone 5: Integrated with Security Controller API.
"""
import streamlit as st
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def _fetch_tools(agent_id: str) -> List[Dict]:
    """
    Fetch tools from Security Controller API.
    Falls back to mock data if API fails.
    """
    try:
        from services.security_controller_client import security_controller_client
        
        response = security_controller_client.get_agent_tools(agent_id)
        tools = response.get('tools', [])
        
        if tools:
            # Transform API response to component format
            return [
                {
                    'name': tool.get('name', tool.get('tool_id', 'unknown')),
                    'type': tool.get('tool_type', tool.get('type', 'READ')),
                    'description': tool.get('description', 'No description'),
                }
                for tool in tools
            ]
        else:
            logger.info(f"No tools returned from API for {agent_id}, using mock data")
            return _get_mock_tools(agent_id)
            
    except Exception as e:
        logger.error(f"Failed to fetch tools from API for {agent_id}: {e}")
        return _get_mock_tools(agent_id)


def render(agent_id: Optional[str] = None, tools: List[Dict] = None):
    """
    Render the Agent Tools panel.
    
    Args:
        agent_id: Agent ID to fetch tools for.
        tools: List of tool dictionaries.
               If None, fetches from API (with fallback to mock data).
    """
    if tools is None:
        tools = _fetch_tools(agent_id) if agent_id else []
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Allowed Tools")
    
    if not tools:
        st.info("No tools configured for this agent")
        if st.button("➕ Add Tool", key="add_tool_empty"):
            st.info("Add Tool functionality coming soon")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    # Render each tool with styling
    for idx, tool in enumerate(tools):
        _render_tool_item(tool, idx)
    
    st.markdown("---")
    
    # Add Tool button
    if st.button("➕ Add Tool", key="add_tool", use_container_width=True):
        st.info("Add Tool functionality coming soon")
    
    st.markdown('</div>', unsafe_allow_html=True)


def _render_tool_item(tool: Dict, idx: int):
    """
    Render a single tool item with hybrid styling.
    
    Args:
        tool: Tool dictionary.
        idx: Index for unique keys.
    """
    # Tool type badge class
    tool_type = tool.get('type', 'READ')
    badge_class = "success" if tool_type == "READ" else "warning"
    
    # Visual wrapper with CSS classes
    st.markdown(f'''
        <div class="tool-row">
            <div class="tool-left">
                <div class="tool-badge {badge_class}">
                    ✅ {tool["name"]}
                </div>
                <span class="status-badge {badge_class}">{tool_type}</span>
            </div>
        </div>
    ''', unsafe_allow_html=True)
    
    # Tool description
    description = tool.get('description', 'No description')
    st.markdown(f'<div class="muted" style="margin-bottom: 12px;">{description}</div>', unsafe_allow_html=True)
    
    # Action buttons (Streamlit widgets for interactivity)
    col1, col2, col_spacer = st.columns([1, 1, 2])
    
    with col1:
        if st.button("⚙️ Configure", key=f"configure_tool_{idx}", use_container_width=True):
            st.info("Configure Tool functionality coming soon")
    
    with col2:
        if st.button("🗑️ Remove", key=f"remove_tool_{idx}", use_container_width=True):
            st.info("Remove Tool functionality coming soon")
    
    st.markdown("---")


def _get_mock_tools(agent_id: Optional[str]) -> List[Dict]:
    """Get mock tools data based on agent ID."""
    if agent_id == "customer-query-agent":
        return [
            {
                "name": "query_customers",
                "type": "READ",
                "description": "Query customer database with filters"
            },
            {
                "name": "query_orders",
                "type": "READ",
                "description": "Query order history for customers"
            },
            {
                "name": "query_with_limit",
                "type": "READ",
                "description": "Query with row limit enforcement"
            },
        ]
    elif agent_id == "payment-agent":
        return [
            {
                "name": "check_order",
                "type": "READ",
                "description": "Check order status and details"
            },
            {
                "name": "process_refund",
                "type": "WRITE",
                "description": "Process customer refunds"
            },
            {
                "name": "process_payment",
                "type": "WRITE",
                "description": "Process payment transactions"
            },
        ]
    else:
        return []
