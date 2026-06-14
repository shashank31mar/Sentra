"""
Sigma Rules Manager - Table view with bulk actions.
"""
import streamlit as st
import pandas as pd
from typing import List, Dict
from services.security_controller_client import SecurityControllerClient


def render(rules: List[Dict], match_range: str = "24h") -> None:
    """Render Sigma rules table with bulk actions.

    Args:
        rules: Sigma rule dicts (id, name, severity, status, match_count, pattern_count).
        match_range: Window the match counts cover (1h/24h/7d/30d) — used for the
            column label so it's honest about what the number means.
    """
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

    _RANGE_LABELS = {"1h": "1h", "24h": "24h", "7d": "7d", "30d": "30d"}
    matches_col = f"Matches ({_RANGE_LABELS.get(match_range, match_range)})"

    # Table view
    df = pd.DataFrame([{
        'Select': False,
        'Name': r.get('name', 'Unnamed'),
        'Severity': r.get('severity', 'medium'),
        'Status': r.get('status', 'active'),
        matches_col: r.get('match_count', 0),
        'Patterns': r.get('pattern_count', 0),
        'rule_id': r.get('id')
    } for r in rules])

    edited_df = st.data_editor(
        df[['Select', 'Name', 'Severity', 'Status', matches_col, 'Patterns']],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", default=False),
            "Status": st.column_config.TextColumn("Status", disabled=True),
            "Severity": st.column_config.TextColumn("Severity", disabled=True),
        },
        hide_index=True,
        use_container_width=True
    )

    # Per-rule detail: show what each rule actually matches on (detection
    # selections + their patterns), fetched from S3 on demand.
    st.markdown("#### 🔎 Rule Details")
    rule_options = {r.get('id'): r.get('name', r.get('id')) for r in rules}
    selected_rule = st.selectbox(
        "Inspect a rule's detection patterns",
        options=list(rule_options.keys()),
        format_func=lambda rid: rule_options.get(rid, rid),
        key="sigma_rules_detail_select",
    )
    if selected_rule:
        _render_rule_detail(selected_rule)

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


def _render_rule_detail(rule_id: str) -> None:
    """Fetch and render a rule's detection selections/patterns."""
    client = SecurityControllerClient()
    resp = client.get_sigma_rule_content(rule_id)
    if not resp.get('success'):
        st.warning(f"Could not load rule details: {resp.get('error', 'unknown error')}")
        return

    data = resp.get('data', {})
    selections = data.get('selections', [])
    cols = st.columns(3)
    cols[0].metric("Severity", str(data.get('level', '—')).upper())
    cols[1].metric("Patterns", data.get('patterns_total', 0))
    cols[2].metric("Condition", str(data.get('condition', '—')))

    if data.get('description'):
        st.caption(data['description'])

    tags = data.get('tags') or []
    if tags:
        st.markdown("**Tags:** " + ", ".join(f"`{t}`" for t in tags))

    if not selections:
        st.info("This rule has no detectable patterns (or content is unavailable).")
        return

    for sel in selections:
        title = f"{sel.get('name', 'selection')} — `{sel.get('field', '')}` ({len(sel.get('patterns', []))})"
        with st.expander(title):
            patterns = sel.get('patterns', [])
            # Render as a code block so substrings with special chars are clear.
            st.code("\n".join(str(p) for p in patterns) or "(empty)", language="text")


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
