"""
Activity Feed Component - Display latest activity logs.
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


def render(logs: List[Dict] = None, limit: int = 5, use_real_data: bool = True):
    """
    Render the Live Activity Feed.
    
    Args:
        logs: List of log entry dictionaries.
              If None, fetches real data or uses mock data.
        limit: Maximum number of entries to display (default: 5).
        use_real_data: If True, fetch real data from CloudWatch.
    """
    if logs is None:
        if use_real_data:
            logs = _get_real_logs(limit)
        else:
            logs = _get_mock_logs()
    
    # Limit to specified number
    logs = logs[:limit]
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader(f"Live Activity Feed (Latest {limit})")
    
    if not logs:
        st.info("No activity yet")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    # Render each log entry with new styling
    for log in logs:
        _render_log_entry(log)
    
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
        key="activity_feed_view_more",
        on_click=_navigate_to_audit
    )
    
    st.markdown('</div>', unsafe_allow_html=True)


def _render_log_entry(log: Dict):
    """Render a single log entry with new CSS classes."""
    # Decision class and icon
    if log["decision"] == "ALLOW":
        feed_class = "feed-allow"
        icon = "✅"
    elif log["decision"] == "DENY":
        feed_class = "feed-deny"
        icon = "🚫"
    else:  # WARNING
        feed_class = "feed-warning"
        icon = "⚠️"
    
    # Format timestamp
    timestamp = log.get("timestamp", "10:45:32")
    
    # Build entry HTML with CSS classes
    html = f'''
    <div class="feed-row {feed_class}">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-weight: 600; font-size: 0.95em;">
                {icon} {timestamp}
            </span>
            <span class="status-badge {'success' if log['decision'] == 'ALLOW' else 'danger' if log['decision'] == 'DENY' else 'warning'}">
                {log["decision"]}
            </span>
        </div>
        <div class="muted">
            <strong>Tool:</strong> {log["tool_name"]}<br>
            <strong>Agent:</strong> {log["agent"]}
    '''
    
    # Add reason if DENY
    if log["decision"] == "DENY" and "reason" in log:
        html += f'<br><strong>Reason:</strong> <span style="color: var(--danger);">{log["reason"]}</span>'
    
    # Add warning if present
    if "warning" in log:
        html += f'<br><span style="color: var(--warning);">⚠️ {log["warning"]}</span>'
    
    html += '''
        </div>
    </div>
    '''
    
    st.markdown(html, unsafe_allow_html=True)


def _get_real_logs(limit: int = 5) -> List[Dict]:
    """Get real log data from Security Controller."""
    _init_clients()  # Ensure clients are initialized
    try:
        logs_data = security_controller_client.get_logs(limit=limit)
        logs = logs_data.get('logs', [])
        
        # Format logs for display
        formatted_logs = []
        for log in logs:
            # Parse timestamp
            timestamp_str = log.get('timestamp', '')
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    timestamp_display = timestamp.strftime("%H:%M:%S")
                except:
                    timestamp_display = timestamp_str[:8]  # Fallback
            else:
                timestamp_display = "N/A"
            
            formatted_log = {
                "timestamp": timestamp_display,
                "decision": log.get('decision', 'UNKNOWN'),
                "tool_name": log.get('tool_name', 'unknown'),
                "agent": log.get('agent_id', 'unknown'),
            }
            
            # Add reason if DENY
            if log.get('decision') == 'DENY':
                formatted_log["reason"] = log.get('reason', 'No reason provided')
            
            # Add warning if present
            if log.get('warning'):
                formatted_log["warning"] = log.get('warning')
            
            formatted_logs.append(formatted_log)
        
        # If no logs found, return empty list (not mock data)
        if not formatted_logs:
            return []
        
        return formatted_logs
    
    except Exception as e:
        logger.error(f"Error fetching real logs: {e}")
        return _get_mock_logs()


def _get_mock_logs() -> List[Dict]:
    """Get mock log data for testing."""
    now = datetime.now()
    
    return [
        {
            "timestamp": (now - timedelta(seconds=7)).strftime("%H:%M:%S"),
            "decision": "ALLOW",
            "tool_name": "query_customers",
            "agent": "customer-query-agent",
        },
        {
            "timestamp": (now - timedelta(seconds=11)).strftime("%H:%M:%S"),
            "decision": "DENY",
            "tool_name": "process_refund",
            "agent": "payment-agent",
            "reason": "Prompt injection detected",
        },
        {
            "timestamp": (now - timedelta(seconds=14)).strftime("%H:%M:%S"),
            "decision": "ALLOW",
            "tool_name": "check_order",
            "agent": "payment-agent",
        },
        {
            "timestamp": (now - timedelta(seconds=19)).strftime("%H:%M:%S"),
            "decision": "ALLOW",
            "tool_name": "query_orders",
            "agent": "customer-query-agent",
            "warning": "High query limit",
        },
        {
            "timestamp": (now - timedelta(seconds=24)).strftime("%H:%M:%S"),
            "decision": "ALLOW",
            "tool_name": "query_customers",
            "agent": "customer-query-agent",
        },
    ]
