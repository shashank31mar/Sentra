"""
Rollback Panel Component - Display rollbackable actions.
"""
import streamlit as st
from datetime import datetime, timedelta
from typing import List, Dict
import logging

from services import security_controller_client

logger = logging.getLogger(__name__)


def _init_clients():
    """Initialize clients if not already initialized."""
    from services.security_controller_client import _get_client
    _get_client()


def render(actions: List[Dict] = None, limit: int = 5, use_real_data: bool = True):
    """
    Render the Rollback Management Panel.
    
    Args:
        actions: List of rollbackable action dictionaries.
                If None, fetches real data or uses mock data.
        limit: Maximum number of entries to display (default: 5).
        use_real_data: If True, fetch real data from CloudWatch.
    """
    if actions is None:
        if use_real_data:
            actions = _get_real_actions(limit)
        else:
            actions = _get_mock_actions()
    
    # Limit to specified number
    actions = actions[:limit]
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader(f"Rollback Management (Latest {limit})")
    
    if not actions:
        st.info("No rollbackable actions yet")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    # Render table header
    st.markdown("""
    <div style="display: grid; grid-template-columns: 1fr 1.5fr 1fr 1fr 1fr 1fr; 
                gap: 8px; padding: 8px; background-color: #f3f4f6; 
                border-radius: 4px; font-weight: 600; font-size: 0.85em; margin-bottom: 8px;">
        <div>Timestamp</div>
        <div>Action</div>
        <div>Resource</div>
        <div>Amount</div>
        <div>Status</div>
        <div>Action</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Show rollback confirmation dialog if requested
    if st.session_state.get('show_rollback_dialog', False):
        _render_rollback_dialog()
    
    # Render each action
    for idx, action in enumerate(actions):
        _render_action_row(action, idx)
    
    # Link to Audit tab
    st.markdown("---")
    def _navigate_to_audit():
        from utils.nav import set_target_tab_in_url
        st.session_state["active_tab"] = "audit"  # single source of truth
        st.session_state["_url_tab_applied"] = False  # allow URL to be re-applied
        set_target_tab_in_url("audit")
        return  # end render cleanly
    
    st.button(
        "View More in Audit Tab →",
        key="rollback_panel_view_more",
        on_click=_navigate_to_audit
    )
    
    st.markdown('</div>', unsafe_allow_html=True)


def _render_rollback_dialog():
    """Render rollback confirmation dialog."""
    action = st.session_state.get('rollback_action', {})
    
    st.markdown("### 🔄 Confirm Rollback")
    st.warning("⚠️ This action will reverse the following operation:")
    
    # Show action details
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Action:** {action.get('action', 'N/A')}")
        st.markdown(f"**Resource:** {action.get('resource', 'N/A')}")
    with col2:
        st.markdown(f"**Amount:** {action.get('amount', 'N/A')}")
        st.markdown(f"**Timestamp:** {action.get('timestamp', 'N/A')}")
    
    # Reason input (required)
    reason = st.text_area(
        "Reason for rollback (required)",
        placeholder="e.g., Customer requested refund reversal, fraudulent transaction, etc.",
        key="rollback_reason",
        height=100,
    )
    
    # Action buttons
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("✅ Confirm Rollback", use_container_width=True, type="primary", disabled=not reason.strip()):
            _execute_rollback(action, reason.strip())
    
    with col_btn2:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.show_rollback_dialog = False
            st.session_state.rollback_action = None
            # No st.rerun() needed - dialog will close on next render


def _execute_rollback(action: Dict, reason: str):
    """Execute the rollback action."""
    from utils.auth import get_user_email
    
    try:
        # Get operator email
        operator_email = get_user_email()
        
        # Call rollback API
        client = security_controller_client.SecurityControllerClient()
        response = client.rollback_action(
            request_id=action.get('request_id', ''),
            reason=reason,
            operator_id=operator_email,
        )
        
        # Check response
        if response.get('success'):
            st.success(f"✓ Rollback successful for {action.get('resource', 'resource')}")
            logger.info(f"Rollback successful: {action.get('request_id')} by {operator_email}")
        else:
            error_msg = response.get('error', 'Unknown error')
            st.error(f"✗ Rollback failed: {error_msg}")
            logger.error(f"Rollback failed: {error_msg}")
        
        # Close dialog
        st.session_state.show_rollback_dialog = False
        st.session_state.rollback_action = None
        # No st.rerun() needed - dialog will close on next render
        
    except Exception as e:
        logger.error(f"Error executing rollback: {e}")
        st.error(f"✗ Rollback failed: {str(e)}")


def _render_action_row(action: Dict, idx: int):
    """Render a single action row."""
    # Status color
    status_colors = {
        "COMPLETED": "#10b981",
        "ROLLED_BACK": "#6b7280",
        "PENDING": "#f59e0b",
        "FAILED": "#ef4444",
    }
    status_color = status_colors.get(action["status"], "#6b7280")
    
    # Create columns for the row
    cols = st.columns([1, 1.5, 1, 1, 1, 1])
    
    with cols[0]:
        st.markdown(f'<div style="font-size: 0.85em; padding: 8px 0;">{action["timestamp"]}</div>', 
                   unsafe_allow_html=True)
    
    with cols[1]:
        st.markdown(
            f'<div style="font-size: 0.85em; padding: 8px 0;">'
            f'<strong>{action["action"]}</strong><br>'
            f'<span style="color: #6b7280; font-size: 0.9em;">Agent: {action["agent"]}</span>'
            f'</div>',
            unsafe_allow_html=True
        )
    
    with cols[2]:
        st.markdown(f'<div style="font-size: 0.85em; padding: 8px 0;">{action["resource"]}</div>', 
                   unsafe_allow_html=True)
    
    with cols[3]:
        st.markdown(f'<div style="font-size: 0.85em; padding: 8px 0;">{action["amount"]}</div>', 
                   unsafe_allow_html=True)
    
    with cols[4]:
        st.markdown(
            f'<div style="font-size: 0.85em; padding: 8px 0;">'
            f'<span style="color: {status_color}; font-weight: 600;">{action["status"]}</span>',
            unsafe_allow_html=True
        )
        if action["status"] == "ROLLED_BACK" and "operator" in action:
            st.markdown(
                f'<div style="font-size: 0.75em; color: #6b7280;">By: {action["operator"]}</div>',
                unsafe_allow_html=True
            )
    
    with cols[5]:
        # Show rollback button only for COMPLETED actions
        if action["status"] == "COMPLETED":
            if st.button("Rollback", key=f"rollback_{idx}", type="secondary"):
                # Store action details for confirmation dialog
                st.session_state.rollback_action = action
                st.session_state.rollback_action_idx = idx
                st.session_state.show_rollback_dialog = True
                # No st.rerun() needed - dialog will open on next render
        elif action["status"] == "ROLLED_BACK":
            st.markdown('<div style="font-size: 0.85em; color: #6b7280;">—</div>', 
                       unsafe_allow_html=True)


def _get_real_actions(limit: int = 5) -> List[Dict]:
    """Get real rollbackable actions from Security Controller."""
    _init_clients()  # Ensure clients are initialized
    try:
        # Query for WRITE operations that were ALLOWED
        logs_data = security_controller_client.get_logs(
            limit=limit * 2,  # Get more to filter
            decision="ALLOW"
        )
        logs = logs_data.get('logs', [])
        
        # Filter for rollbackable actions (WRITE operations)
        rollbackable_actions = []
        for log in logs:
            # Check if this is a WRITE operation
            operation_type = log.get('operation_type', '')
            tool_name = log.get('tool_name', '')
            
            # Consider refund, payment, update operations as rollbackable
            if operation_type == 'WRITE' or any(keyword in tool_name.lower() 
                for keyword in ['refund', 'payment', 'update', 'delete', 'process']):
                
                # Parse timestamp
                timestamp_str = log.get('timestamp', '')
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        timestamp_display = timestamp.strftime("%H:%M:%S")
                    except:
                        timestamp_display = timestamp_str[:8]
                else:
                    timestamp_display = "N/A"
                
                # Extract resource and amount from tool_params if available
                tool_params = log.get('tool_params', {})
                if isinstance(tool_params, str):
                    import json
                    try:
                        tool_params = json.loads(tool_params)
                    except:
                        tool_params = {}
                
                resource = tool_params.get('order_id', tool_params.get('resource_id', 'N/A'))
                amount = tool_params.get('amount', 'N/A')
                if isinstance(amount, (int, float)):
                    amount = f"${amount:.2f}"
                
                # Check if already rolled back
                status = log.get('rollback_status', 'COMPLETED')
                
                action = {
                    "timestamp": timestamp_display,
                    "action": tool_name,
                    "agent": log.get('agent_id', 'unknown'),
                    "resource": str(resource),
                    "amount": str(amount),
                    "status": status,
                    "request_id": log.get('request_id', ''),
                }
                
                if status == "ROLLED_BACK":
                    action["operator"] = log.get('operator_id', 'unknown')
                
                rollbackable_actions.append(action)
                
                if len(rollbackable_actions) >= limit:
                    break
        
        # If no actions found, return empty list (not mock data)
        if not rollbackable_actions:
            return []
        
        return rollbackable_actions
    
    except Exception as e:
        logger.error(f"Error fetching real rollbackable actions: {e}")
        return _get_mock_actions()


def _get_mock_actions() -> List[Dict]:
    """Get mock rollbackable actions for testing."""
    now = datetime.now()
    
    return [
        {
            "timestamp": (now - timedelta(minutes=3, seconds=17)).strftime("%H:%M:%S"),
            "action": "process_refund",
            "agent": "payment-agent",
            "resource": "#12345",
            "amount": "$50.00",
            "status": "COMPLETED",
        },
        {
            "timestamp": (now - timedelta(minutes=6, seconds=50)).strftime("%H:%M:%S"),
            "action": "process_refund",
            "agent": "payment-agent",
            "resource": "#12346",
            "amount": "$125.00",
            "status": "COMPLETED",
        },
        {
            "timestamp": (now - timedelta(minutes=10, seconds=22)).strftime("%H:%M:%S"),
            "action": "process_refund",
            "agent": "payment-agent",
            "resource": "#12344",
            "amount": "$75.00",
            "status": "ROLLED_BACK",
            "operator": "ops-alice",
        },
        {
            "timestamp": (now - timedelta(minutes=15, seconds=27)).strftime("%H:%M:%S"),
            "action": "process_refund",
            "agent": "payment-agent",
            "resource": "#12343",
            "amount": "$125.00",
            "status": "COMPLETED",
        },
        {
            "timestamp": (now - timedelta(minutes=20, seconds=2)).strftime("%H:%M:%S"),
            "action": "process_refund",
            "agent": "payment-agent",
            "resource": "#12342",
            "amount": "$200.00",
            "status": "COMPLETED",
        },
    ]
