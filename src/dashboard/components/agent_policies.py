"""
Agent Policies Component - Display and manage agent policies.

Milestone 5: Integrated with Security Controller API.
Workstream 11: Added CRUD operations (create/edit/delete).
Shows complete policy document (YAML/JSON) including allowed tools and policy rules.
"""
import streamlit as st
from typing import Dict, Optional
import logging
import json
import yaml

logger = logging.getLogger(__name__)


def _fetch_policy_document(agent_id: str) -> Optional[Dict]:
    """
    Fetch complete policy document from Security Controller API.
    Returns the full policy document (metadata + content) or None.
    """
    try:
        from services.security_controller_client import security_controller_client
        
        # First, query policies by agent_id to get the policy_id
        logger.info(f"Fetching policies for agent_id: {agent_id}")
        response = security_controller_client.get_policies(agent_id=agent_id)
        logger.info(f"get_policies response: {response}")
        
        # get_policies returns the data directly (not wrapped in success)
        policies = response.get('policies', [])
        logger.info(f"Found {len(policies)} policies for agent {agent_id}")
        
        if len(policies) == 0:
            logger.info(f"No policies found for agent {agent_id}")
            return None
        
        # Get the first policy (should only be one per agent)
        policy_metadata = policies[0]
        logger.info(f"Policy metadata: {policy_metadata}")
        policy_id = policy_metadata.get('policy_id')
        
        if not policy_id:
            logger.error(f"Policy metadata missing policy_id for agent {agent_id}")
            return None
        
        # Now fetch the full policy document with content
        logger.info(f"Fetching full policy document for policy_id: {policy_id}")
        full_response = security_controller_client.get_policy_by_id(policy_id, include_content=True)
        logger.info(f"get_policy_by_id response: {full_response}")
        
        if full_response.get('success'):
            policy_doc = full_response.get('policy', {})
            logger.info(f"Successfully fetched policy document with keys: {policy_doc.keys()}")
            return policy_doc
        else:
            logger.error(f"Failed to fetch full policy for {policy_id}: {full_response.get('error')}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to fetch policy from API for {agent_id}: {e}", exc_info=True)
        return None


def render(agent_id: Optional[str] = None):
    """
    Render the Agent Policy panel - shows complete policy document.
    
    Args:
        agent_id: Agent ID to fetch policy for.
    """
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Agent Policy Configuration")
    
    if not agent_id:
        st.info("Select an agent to view policy configuration")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    # Fetch complete policy document
    policy_doc = _fetch_policy_document(agent_id)
    
    if not policy_doc:
        st.info("No policy configured for this agent")
        if st.button("➕ Create Policy", key="create_policy_empty", use_container_width=True):
            st.session_state['create_policy_modal'] = True
            st.rerun()

        # Show create modal if active
        if st.session_state.get('create_policy_modal', False):
            _render_create_policy_modal(agent_id)

        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    # Render policy document summary and full content
    _render_policy_document(agent_id, policy_doc)

    st.markdown('</div>', unsafe_allow_html=True)


def _render_policy_document(agent_id: str, policy_doc: Dict):
    """
    Render complete policy document with summary and full content.
    
    Args:
        agent_id: Agent ID
        policy_doc: Complete policy document (metadata + content)
    """
    metadata = policy_doc.get('metadata', {})
    content = policy_doc.get('content', {})
    
    policy_id = metadata.get('policy_id', f'agent-config-{agent_id}')
    
    # Policy summary header
    status = metadata.get('status', 'active')
    status_badge_map = {
        "active": "success",
        "disabled": "info",
    }
    status_badge_class = status_badge_map.get(status, "info")
    
    st.markdown(f'''
        <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 16px;">
            <strong style="font-size: 16px;">📋 {metadata.get('name', 'Agent Policy')}</strong>
            <span class="status-badge {status_badge_class}">{status.upper()}</span>
            <span class="muted">v{metadata.get('version', '1.0.0')}</span>
        </div>
    ''', unsafe_allow_html=True)
    
    # Quick stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Allowed Tools", metadata.get('allowed_tools_count', 0))
    with col2:
        st.metric("Policy Rules", metadata.get('policies_count', 0))
    with col3:
        severity = metadata.get('severity_breakdown', {})
        critical_high = severity.get('critical', 0) + severity.get('high', 0)
        st.metric("Critical/High", critical_high)
    
    st.markdown("---")
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("✏️ Edit Policy", key=f"edit_policy_{policy_id}", use_container_width=True):
            st.session_state[f'edit_policy_modal_{policy_id}'] = True
            st.rerun()
    
    with col2:
        if st.button("🗑️ Delete Policy", key=f"delete_policy_{policy_id}", use_container_width=True):
            st.session_state[f'confirm_delete_{policy_id}'] = True
            st.rerun()
    
    # Show delete confirmation dialog
    if st.session_state.get(f'confirm_delete_{policy_id}', False):
        _render_delete_confirmation_dialog(policy_id, metadata.get('name', 'Policy'))
    
    # Show edit modal
    if st.session_state.get(f'edit_policy_modal_{policy_id}', False):
        _render_edit_policy_modal(policy_id, content)
    
    st.markdown("---")
    
    # Show full policy content in expandable section
    with st.expander("📄 View Full Policy Document", expanded=False):
        # Format selector
        format_choice = st.radio(
            "Display format:",
            options=["YAML", "JSON"],
            horizontal=True,
            key=f"format_{policy_id}"
        )
        
        if format_choice == "YAML":
            import yaml
            yaml_content = yaml.dump(content, sort_keys=False, default_flow_style=False)
            st.code(yaml_content, language="yaml")
        else:
            st.json(content)
    
    # Show allowed tools summary
    allowed_tools = content.get('allowed_tools', [])
    if allowed_tools:
        with st.expander(f"🔧 Allowed Tools ({len(allowed_tools)})", expanded=False):
            for tool in allowed_tools:
                st.markdown(f"- `{tool}`")
    
    # Show policy rules summary
    policies = content.get('policies', [])
    if policies:
        with st.expander(f"📋 Policy Rules ({len(policies)})", expanded=True):
            for idx, policy in enumerate(policies):
                severity = policy.get('severity', 'medium')
                action = policy.get('action', 'DENY')
                enabled = policy.get('enabled', True)
                
                severity_badge_map = {
                    'critical': 'danger',
                    'high': 'warning',
                    'medium': 'info',
                    'low': 'success'
                }
                severity_badge = severity_badge_map.get(severity, 'info')
                action_badge = 'danger' if action == 'DENY' else 'success'
                enabled_badge = 'success' if enabled else 'info'
                
                st.markdown(f'''
                    <div style="padding: 12px; border-left: 3px solid #ddd; margin-bottom: 12px; background: #f8f9fa;">
                        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 6px;">
                            <strong>{policy.get('name', f'Rule {idx+1}')}</strong>
                            <span class="status-badge {severity_badge}">{severity.upper()}</span>
                            <span class="status-badge {action_badge}">{action}</span>
                            <span class="status-badge {enabled_badge}">{'ENABLED' if enabled else 'DISABLED'}</span>
                        </div>
                        <div class="muted" style="margin-top: 6px;">
                            <strong>Rule:</strong> <code>{policy.get('rule', 'N/A')}</code>
                        </div>
                        <div class="muted" style="margin-top: 4px;">
                            {policy.get('description', 'No description')}
                        </div>
                    </div>
                ''', unsafe_allow_html=True)





# ============================================================
# Workstream 11: Policy CRUD UI Functions
# ============================================================

def _render_delete_confirmation_dialog(policy_id: str, policy_name: str):
    """Render delete confirmation dialog."""
    with st.container():
        st.warning(f"⚠️ Are you sure you want to delete policy **{policy_name}**?")
        st.caption("This will soft-delete the policy (mark as disabled). The audit trail will be preserved.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Yes, Delete", key=f"confirm_delete_yes_{policy_id}", use_container_width=True):
                _handle_delete_policy(policy_id)
                st.session_state[f'confirm_delete_{policy_id}'] = False
                st.rerun()

        with col2:
            if st.button("❌ Cancel", key=f"confirm_delete_no_{policy_id}", use_container_width=True):
                st.session_state[f'confirm_delete_{policy_id}'] = False
                st.rerun()


def _handle_delete_policy(policy_id: str):
    """Handle policy deletion."""
    try:
        from services.security_controller_client import security_controller_client

        result = security_controller_client.delete_policy(policy_id)

        if result.get('success'):
            st.success(f"✅ {result.get('message', 'Policy deleted successfully')}")
            st.cache_data.clear()  # Clear cache to refresh policies
        else:
            st.error(f"❌ Failed to delete policy: {result.get('error', 'Unknown error')}")

    except Exception as e:
        logger.error(f"Error deleting policy {policy_id}: {e}")
        st.error(f"❌ Error: {str(e)}")


def _handle_disable_policy(policy_id: str):
    """Handle policy disable (soft delete)."""
    _handle_delete_policy(policy_id)


def _render_edit_policy_modal(policy_id: str, policy_content: Dict):
    """Render edit policy modal with YAML/JSON editor."""
    with st.container():
        st.markdown("### ✏️ Edit Policy")
        st.caption(f"Editing: **{policy_content.get('name', policy_id)}**")

        try:
            # Format selector
            format_choice = st.radio(
                "Edit format:",
                options=["YAML", "JSON"],
                horizontal=True,
                key=f"edit_format_{policy_id}"
            )
            
            # Convert to selected format
            if format_choice == "YAML":
                import yaml
                policy_text = yaml.dump(policy_content, sort_keys=False, default_flow_style=False)
                language = "yaml"
            else:
                policy_text = json.dumps(policy_content, indent=2)
                language = "json"
            
            # Editor
            edited_text = st.text_area(
                f"Policy {format_choice}",
                value=policy_text,
                height=500,
                key=f"edit_text_{policy_id}",
                help=f"Edit the policy {format_choice}. Ensure valid {format_choice} format."
            )

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if st.button("💾 Save Changes", key=f"save_edit_{policy_id}", use_container_width=True):
                    _handle_save_policy(policy_id, edited_text, format_choice)

            with col2:
                if st.button("❌ Cancel", key=f"cancel_edit_{policy_id}", use_container_width=True):
                    st.session_state[f'edit_policy_modal_{policy_id}'] = False
                    st.rerun()

        except Exception as e:
            logger.error(f"Error loading policy for edit: {e}")
            st.error(f"❌ Error: {str(e)}")


def _handle_save_policy(policy_id: str, policy_text: str, format_type: str):
    """Handle saving edited policy."""
    try:
        # Parse based on format
        try:
            if format_type == "YAML":
                import yaml
                policy_data = yaml.safe_load(policy_text)
            else:
                policy_data = json.loads(policy_text)
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            st.error(f"❌ Invalid {format_type}: {str(e)}")
            return

        # Call API to update policy
        from services.security_controller_client import security_controller_client

        result = security_controller_client.update_policy(policy_id, policy_data)

        if result.get('success'):
            st.success(f"✅ {result.get('message', 'Policy updated successfully')}")
            st.session_state[f'edit_policy_modal_{policy_id}'] = False
            st.cache_data.clear()  # Clear cache to refresh policies
            st.rerun()
        else:
            error_msg = result.get('error', 'Unknown error')
            details = result.get('details', [])
            st.error(f"❌ Failed to update policy: {error_msg}")
            if details:
                st.json(details)

    except Exception as e:
        logger.error(f"Error saving policy {policy_id}: {e}")
        st.error(f"❌ Error: {str(e)}")


def _render_create_policy_modal(agent_id: str):
    """Render create policy modal with YAML/JSON editor."""
    with st.container():
        st.markdown("### ➕ Create New Policy")
        st.caption(f"Creating policy for agent: **{agent_id}**")

        # Sample policy template
        sample_policy = {
            "schema_version": "v1",
            "agent_id": agent_id or "your-agent-id",
            "name": "New Policy",
            "version": "1.0.0",
            "description": "Policy description",
            "allowed_tools": [
                "tool_1",
                "tool_2"
            ],
            "policies": [
                {
                    "policy_id": "pol-001",
                    "name": "Sample Policy Rule",
                    "description": "Sample rule description",
                    "rule": "parameter_value <= 1000",
                    "action": "DENY",
                    "severity": "high",
                    "enabled": True
                }
            ]
        }

        # Format selector
        format_choice = st.radio(
            "Create format:",
            options=["YAML", "JSON"],
            horizontal=True,
            key="create_format"
        )
        
        # Convert to selected format
        if format_choice == "YAML":
            import yaml
            policy_text = yaml.dump(sample_policy, sort_keys=False, default_flow_style=False)
        else:
            policy_text = json.dumps(sample_policy, indent=2)
        
        edited_text = st.text_area(
            f"Policy {format_choice}",
            value=policy_text,
            height=500,
            key="create_policy_text",
            help=f"Edit the policy {format_choice}. Follow the schema format above."
        )

        st.caption("💡 **Tip**: Update `agent_id`, `name`, `allowed_tools`, and `policies` array before saving.")

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 Create Policy", key="save_create_policy", use_container_width=True):
                _handle_create_policy(edited_text, format_choice)

        with col2:
            if st.button("❌ Cancel", key="cancel_create_policy", use_container_width=True):
                st.session_state['create_policy_modal'] = False
                st.rerun()


def _handle_create_policy(policy_text: str, format_type: str):
    """Handle creating new policy."""
    try:
        # Parse based on format
        try:
            if format_type == "YAML":
                import yaml
                policy_data = yaml.safe_load(policy_text)
            else:
                policy_data = json.loads(policy_text)
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            st.error(f"❌ Invalid {format_type}: {str(e)}")
            return

        # Call API to create policy
        from services.security_controller_client import security_controller_client

        result = security_controller_client.create_policy(policy_data)

        if result.get('success'):
            st.success(f"✅ {result.get('message', 'Policy created successfully')}")
            st.session_state['create_policy_modal'] = False
            st.cache_data.clear()  # Clear cache to refresh policies
            st.rerun()
        else:
            error_msg = result.get('error', 'Unknown error')
            details = result.get('details', [])
            st.error(f"❌ Failed to create policy: {error_msg}")
            if details:
                st.json(details)

    except Exception as e:
        logger.error(f"Error creating policy: {e}")
        st.error(f"❌ Error: {str(e)}")
