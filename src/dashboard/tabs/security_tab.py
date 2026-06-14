"""
Security Tab - Threat analysis and Sigma rules management.

Reference: LLD 04 Section 2.6
Milestone 9: Tasks 9.5, 9.6, 9.7, 9.8, 9.9
"""
import streamlit as st
import logging
from typing import Dict, List
from components import threat_summary, sigma_rules_manager, recent_threats
from services.security_controller_client import SecurityControllerClient

logger = logging.getLogger(__name__)


def render():
    """Render the Security tab with threat analysis and Sigma rules."""

    # 2-column layout: Threat Summary (left) + Sigma Rules (right)
    col_left, col_right = st.columns([1, 2])

    with col_left:
        # Fetch and render threat summary (isolated in container to prevent nesting issues)
        threat_data = _fetch_threat_data()
        with st.container():
            threat_summary.render(threat_data)

    with col_right:
        # Match-count time window selector (drives the CloudWatch query that
        # backs the "Matches" column). Default 24h.
        _RANGE_LABELS = {"1h": "Last 1 hour", "24h": "Last 24 hours", "7d": "Last 7 days", "30d": "Last 30 days"}
        range_token = st.selectbox(
            "Match window",
            options=list(_RANGE_LABELS.keys()),
            index=1,  # 24h default
            format_func=lambda t: _RANGE_LABELS[t],
            key="security_tab_sigma_match_range",
        )
        # Fetch and render Sigma rules (isolated in container to prevent nesting issues)
        rules = _fetch_sigma_rules(range_token)
        with st.container():
            sigma_rules_manager.render(rules, match_range=range_token)

    st.markdown("---")

    # Recent threats table
    threats = _fetch_recent_threats()
    recent_threats.render(threats)

    st.markdown("---")

    # Code Attribution placeholder (Phase 2)
    _render_code_attribution_placeholder()


def _fetch_threat_data() -> Dict:
    """
    Fetch threat statistics from Security Controller API.

    Returns:
        Dictionary with threat statistics
    """
    try:
        client = SecurityControllerClient()
        response = client.get_metrics()

        if response.get('success') and response.get('status_code') == 200:
            metrics = response.get('metrics', {})
            threats = metrics.get('threats', {})
            
            logger.info(f"Fetched threat data from API: {threats}")

            # Calculate total threats
            total_threats = sum(threats.values()) if threats else 0
            
            # For MVP, we don't have severity breakdown in metrics
            # So we'll estimate based on threat types
            # In production, this would come from the API
            critical = threats.get('PROMPT_INJECTION', 0) + threats.get('SQL_INJECTION', 0)
            high = threats.get('POLICY_VIOLATION', 0) + threats.get('UNAUTHORIZED_TOOL', 0)
            medium = threats.get('SEQUENCE_VIOLATION', 0) + threats.get('RATE_LIMIT', 0)
            low = 0

            # Transform API response to component format
            return {
                'total': total_threats,
                'critical': critical,
                'high': high,
                'medium': medium,
                'low': low,
                'threat_types': threats,
            }
        else:
            logger.warning("API returned no threat data, using mock data")
            return threat_summary.get_mock_threat_data()

    except Exception as e:
        logger.error(f"Error fetching threat data: {e}")
        st.warning("Using mock data for demo")
        return threat_summary.get_mock_threat_data()


def _fetch_sigma_rules(match_range: str = "24h") -> List[Dict]:
    """
    Fetch Sigma rules from Security Controller API.

    Args:
        match_range: Match-count time window (1h, 24h, 7d, 30d).

    Returns:
        List of Sigma rule dictionaries
    """
    try:
        client = SecurityControllerClient()
        response = client.get_sigma_rules(match_range=match_range)

        if response.get('success') and response.get('status_code') == 200:
            rules = response.get('rules', [])
            logger.info(f"Fetched {len(rules)} Sigma rules from API")

            # The API now returns flat, console-shaped fields (see _to_api_rule):
            # match_count is sourced from CloudWatch for the requested window;
            # patterns_count is the rule's detection-selection count.
            mapped_rules = []
            for rule in rules:
                mapped_rules.append({
                    'id': rule.get('rule_id'),
                    'name': rule.get('title', 'Unnamed Rule'),
                    'status': rule.get('status', 'stable'),
                    'severity': rule.get('severity', 'medium'),
                    'match_count': rule.get('match_count', 0),
                    'pattern_count': rule.get('patterns_count', 0),
                    'description': rule.get('description', ''),
                })

            return mapped_rules if mapped_rules else sigma_rules_manager.get_mock_sigma_rules()
        else:
            logger.warning("API returned no Sigma rules, using mock data")
            return sigma_rules_manager.get_mock_sigma_rules()

    except Exception as e:
        logger.error(f"Error fetching Sigma rules: {e}")
        st.warning("Using mock data for demo")
        return sigma_rules_manager.get_mock_sigma_rules()


def _fetch_recent_threats() -> List[Dict]:
    """
    Fetch recent threats from Security Controller API.

    Returns:
        List of recent threat dictionaries
    """
    try:
        client = SecurityControllerClient()

        # Query logs for threats in last 24 hours
        from datetime import datetime, timedelta
        since = (datetime.now() - timedelta(hours=24)).isoformat()

        response = client.get_logs(
            since=since,
            decision='DENY',  # Only blocked requests (threats)
            limit=10,
        )

        if response.get('success') and response.get('status_code') == 200:
            logs = response.get('logs', [])
            logger.info(f"Fetched {len(logs)} recent threats from API")

            # Transform logs to threat format
            threats = []
            for log in logs:
                threats.append({
                    'timestamp': log.get('timestamp'),
                    'threat_type': log.get('threat_type', 'UNKNOWN'),
                    'agent_id': log.get('agent_id'),
                    'matched_rule': log.get('matched_rule', 'N/A'),
                    'request_id': log.get('request_id'),
                    'severity': log.get('severity', 'medium'),
                })

            return threats if threats else recent_threats.get_mock_recent_threats()
        else:
            logger.warning("API returned no recent threats, using mock data")
            return recent_threats.get_mock_recent_threats()

    except Exception as e:
        logger.error(f"Error fetching recent threats: {e}")
        st.warning("Using mock data for demo")
        return recent_threats.get_mock_recent_threats()


def _render_code_attribution_placeholder() -> None:
    """Render Code Attribution placeholder for Phase 2."""
    st.markdown("### 🔍 Code Attribution (Phase 2 - Coming Soon)")

    st.info("""
    **Planned Features:**
    - 📍 Source code location of matched rules
    - 📦 SBOM (Software Bill of Materials)
    - 🔗 Call stack traces
    - 🏷️ Version tracking and change history
    """)

    st.caption("Code attribution will help trace security events back to specific code changes and dependencies.")
