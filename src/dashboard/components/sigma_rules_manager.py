"""
Sigma Rules Manager - Table view with bulk actions.
"""
import streamlit as st
import pandas as pd
from typing import List, Dict
from services.security_controller_client import SecurityControllerClient


def render(rules: List[Dict]) -> None:
    """Render Sigma rules table with bulk actions."""
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 📋 Sigma Rules Management")

    col1, col2, _ = st.columns([1.5, 1.5, 4])
    with col1:
        if st.button("➕ Add Custom Rule", use_container_width=True):
            st.info("Add Rule (Coming soon)")
    with col2:
        if st.button("📥 Import Rules", use_container_width=True):
            st.info("Import Rules (Coming soon)")

    st.markdown("---")

    if not rules:
        st.info("No Sigma rules configured")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # Table view
    df = pd.DataFrame([{
        'Select': False,
        'Name': r.get('name', 'Unnamed'),
        'Severity': r.get('severity', 'medium'),
        'Status': r.get('status', 'active'),
        'Matches (24h)': r.get('match_count', 0),
        'Patterns': r.get('pattern_count', 0),
        'rule_id': r.get('id')
    } for r in rules])

    edited_df = st.data_editor(
        df[['Select', 'Name', 'Severity', 'Status', 'Matches (24h)', 'Patterns']],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", default=False),
            "Status": st.column_config.TextColumn("Status", disabled=True),
            "Severity": st.column_config.TextColumn("Severity", disabled=True),
        },
        hide_index=True,
        use_container_width=True
    )

    # Bulk actions
    selected_indices = edited_df[edited_df['Select']].index.tolist()
    if selected_indices:
        st.write(f"**{len(selected_indices)} rules selected**")
        col1, col2, col3, _ = st.columns([1, 1, 1, 5])

        with col1:
            if st.button("✅ Enable", use_container_width=True):
                _bulk_update_status(df, selected_indices, 'stable')

        with col2:
            if st.button("🚫 Disable", use_container_width=True):
                _bulk_update_status(df, selected_indices, 'deprecated')

        with col3:
            if st.button("🗑️ Delete", use_container_width=True):
                st.warning("Delete not yet implemented")

    st.markdown('</div>', unsafe_allow_html=True)


def _bulk_update_status(df: pd.DataFrame, indices: List[int], new_status: str):
    """Update status for selected rules."""
    client = SecurityControllerClient()
    for idx in indices:
        rule_id = df.loc[idx, 'rule_id']
        resp = client.update_sigma_rule_status(rule_id, new_status)
        if resp.get('success'):
            st.success(f"✓ Updated {df.loc[idx, 'Name']}")
        else:
            st.error(f"✗ Failed to update {df.loc[idx, 'Name']}")
    st.rerun()


def get_mock_sigma_rules() -> List[Dict]:
    """Mock rules for demo."""
    return [
        {'id': 'r1', 'name': 'Prompt Injection', 'status': 'active', 'severity': 'high', 'match_count': 12, 'pattern_count': 20, 'description': ''},
        {'id': 'r2', 'name': 'Jailbreak', 'status': 'active', 'severity': 'critical', 'match_count': 0, 'pattern_count': 15, 'description': ''},
    ]
